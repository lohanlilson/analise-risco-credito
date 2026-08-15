import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import pandas as pd
import sqlite3
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import os
import re
import tempfile
import webbrowser
import sys 

# Suprimir o aviso de FutureWarning do Pandas para versões mais recentes
try:
    pd.set_option('future.no_silent_downcasting', True)
except Exception:
    pass

# --- FUNÇÃO AUXILIAR DE FORMATAÇÃO MONETÁRIA ---
def format_brl(val):
    """Converte um número para string no formato monetário R$ 1.234,56"""
    if val is None or pd.isna(val): val = 0.0
    return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def limpar_cnpj(valor):
    """Elimina caracteres não numéricos e resolve conversões flutuantes do Pandas"""
    if pd.isna(valor): return ""
    if isinstance(valor, float):
        try: valor = int(valor)
        except: pass
    v_str = str(valor).strip()
    if v_str.endswith('.0'):
        v_str = v_str[:-2]
    return re.sub(r'\D', '', v_str)

# --- DIÁLOGO COM MÁSCARA MONETÁRIA E CURSOR ESTÁVEL ---
class CurrencyInputDialog(simpledialog.Dialog):
    def __init__(self, parent, title, prompt, initial_value=0.0):
        self.prompt_text = prompt
        self.initial_value = initial_value
        self._lock = False 
        super().__init__(parent, title)

    def body(self, master):
        tk.Label(master, text=self.prompt_text, font=("Arial", 10)).grid(row=0, padx=20, pady=10)
        self.v = tk.StringVar()
        self.entry = tk.Entry(master, textvariable=self.v, width=25, font=("Consolas", 14), justify="right")
        self.entry.grid(row=1, padx=20, pady=10)
        
        initial_str = format_brl(self.initial_value).replace("R$ ", "")
        self.v.set(initial_str)
        self.v.trace_add("write", self.on_type)
        
        self.entry.focus_set()
        self.entry.after(50, lambda: self.entry.icursor(tk.END))
        return self.entry

    def on_type(self, *args):
        if self._lock: return
        digits = "".join(re.findall(r'\d', self.v.get()))
        if not digits: new_val = "0,00"
        else:
            try:
                val_float = float(digits) / 100
                new_val = f"{val_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            except ValueError: new_val = "0,00"
        self._lock = True
        self.v.set(new_val)
        self._lock = False
        self.entry.after_idle(lambda: self.entry.icursor(tk.END))

    def apply(self):
        digits = "".join(re.findall(r'\d', self.v.get()))
        self.result = float(digits) / 100 if digits else 0.0

class RiskApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Análise de Riscos")
        self.root.state('zoomed') # Abre sempre maximizado
        
        # GARANTIR O ENCERRAMENTO COMPLETO DO PROCESSO
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.conn = sqlite3.connect('banco_risco.db')
        self.init_db()
        
        self.contexto = "CLIENTE" 
        self.view_filter = "Agregado"
        self.time_filter = "6 Meses" # Filtro Padrão Inicial
        self.full_list_entidades = [] 
        
        self.setup_ui()
        self.atualizar_interface()

    def on_closing(self):
        """Fecha conexões e mata o processo residual no Windows ao fechar o App"""
        try:
            plt.close('all') 
            self.conn.close() 
        except Exception:
            pass
        finally:
            self.root.quit()
            self.root.destroy()
            sys.exit(0) 

    def init_db(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS registros (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo_registro TEXT,
                data_base TEXT,
                base_id TEXT,
                nome_arquivo TEXT,
                entidade_id TEXT,
                nome_entidade TEXT,
                valor_aberto REAL DEFAULT 0,
                valor_vencido REAL DEFAULT 0,
                valor_a_vencer REAL DEFAULT 0,
                valor_quitado REAL DEFAULT 0,
                valor_aquisicao REAL DEFAULT 0,
                data_importacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS titulos_ativos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_cliente TEXT,
                cnpj_sacado TEXT,
                nome_sacado TEXT,
                numero_titulo TEXT,
                vencimento TEXT,
                saldo_titulo REAL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS titulos_completos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contexto TEXT,
                entidade_id TEXT,
                nome_entidade TEXT,
                numero_titulo TEXT,
                data_operacao TEXT,
                vencimento TEXT,
                data_quitacao TEXT,
                valor_titulo REAL,
                saldo_titulo REAL
            )
        ''')
        
        try: cursor.execute('ALTER TABLE registros ADD COLUMN valor_quitado REAL DEFAULT 0')
        except: pass
        try: cursor.execute('ALTER TABLE registros ADD COLUMN valor_aquisicao REAL DEFAULT 0')
        except: pass
        
        try: cursor.execute('ALTER TABLE titulos_completos ADD COLUMN nome_cliente TEXT')
        except: pass
        try: cursor.execute('ALTER TABLE titulos_completos ADD COLUMN nome_sacado TEXT')
        except: pass
        
        cursor.execute('''CREATE TABLE IF NOT EXISTS limites (tipo TEXT, entidade_nome TEXT, valor REAL DEFAULT 0, PRIMARY KEY (tipo, entidade_nome))''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS grupos (tipo TEXT, entidade_id TEXT, nome_grupo TEXT, PRIMARY KEY (tipo, entidade_id, nome_grupo))''')
        self.conn.commit()

    def setup_ui(self):
        prev_search = getattr(self, 'search_var', None)
        search_val = prev_search.get() if prev_search else "TODOS"
        self.search_var = tk.StringVar(value=search_val)

        for widget in self.root.winfo_children():
            widget.destroy()

        # ── Estilos globais ───────────────────────────────────────────────────
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TNotebook',          background='#f1f5f9', borderwidth=0)
        style.configure('TNotebook.Tab',      background='#e2e8f0', foreground='#475569',
                        font=('Segoe UI', 9, 'bold'), padding=[16, 6])
        style.map('TNotebook.Tab',
                  background=[('selected', 'white')],
                  foreground=[('selected', '#0f172a')])
        style.configure('Treeview',           font=('Segoe UI', 9),  rowheight=26,
                        background='white',   fieldbackground='white', foreground='#0f172a')
        style.configure('Treeview.Heading',   font=('Segoe UI', 9, 'bold'),
                        background='#f1f5f9', foreground='#475569')
        style.map('Treeview', background=[('selected', '#dbeafe')])

        self.cor_bg  = "#0d1035" if self.contexto == "CLIENTE" else "#1e1b4b"
        self.cor_acc = "#2563eb" if self.contexto == "CLIENTE" else "#4f46e5"
        BG = "#f1f5f9"   # fundo principal
        WH = "white"

        # ══════════════════════════════════════════════════════════════════════
        # PAINEL LATERAL
        # ══════════════════════════════════════════════════════════════════════
        side = tk.Frame(self.root, bg=self.cor_bg, width=260)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)

        # Logo / título
        tk.Label(side, text="Análise de Riscos", bg=self.cor_bg,
                 fg="white", font=("Segoe UI", 13, "bold")).pack(pady=(22, 2))
        tk.Label(side, text="Nacional Securitizadora", bg=self.cor_bg,
                 fg="#94a3b8", font=("Segoe UI", 8)).pack(pady=(0, 18))

        tk.Frame(side, bg="#1e3a6e", height=1).pack(fill="x", padx=20, pady=4)

        # Modo de análise
        tk.Label(side, text="MODO DE ANÁLISE", bg=self.cor_bg,
                 fg="#94a3b8", font=("Segoe UI", 8, "bold")).pack(pady=(14, 6))
        ctx_frame = tk.Frame(side, bg=self.cor_bg)
        ctx_frame.pack(fill="x", padx=16, pady=(0, 4))

        def _btn_ctx(parent, text, ctx):
            ativo = self.contexto == ctx
            b = tk.Button(parent, text=text,
                          command=lambda: self.switch_contexto(ctx),
                          bg=self.cor_acc if ativo else "#1e293b",
                          fg="white", relief="flat",
                          font=("Segoe UI", 9, "bold"), pady=7, cursor="hand2")
            b.pack(side="left", expand=True, fill="x", padx=2)
        _btn_ctx(ctx_frame, "CLIENTES", "CLIENTE")
        _btn_ctx(ctx_frame, "SACADOS",  "SACADO")

        tk.Frame(side, bg="#1e3a6e", height=1).pack(fill="x", padx=20, pady=14)

        # Botões de ação
        def _btn_side(parent, text, cmd, bg, font_size=9):
            tk.Button(parent, text=text, command=cmd, bg=bg, fg="white",
                      font=("Segoe UI", font_size, "bold"), relief="flat",
                      pady=9, cursor="hand2").pack(fill="x", padx=16, pady=4)

        tk.Label(side, text="CARTEIRAS", bg=self.cor_bg,
                 fg="#94a3b8", font=("Segoe UI", 8, "bold")).pack(pady=(0, 4))
        _btn_side(side, "🚀  Processar Carteiras",    self.importar_lote_dual,       "#ea580c", 10)
        _btn_side(side, "📊  Importar Limites Excel", self.importar_planilha_limites, "#7c3aed")

        tk.Frame(side, bg="#1e3a6e", height=1).pack(fill="x", padx=20, pady=14)

        tk.Label(side, text="GESTÃO", bg=self.cor_bg,
                 fg="#94a3b8", font=("Segoe UI", 8, "bold")).pack(pady=(0, 4))
        _btn_side(side, "👥  Gerenciar Entidades", self.janela_gestao_entidades, "#059669")

        tk.Frame(side, bg="#1e3a6e", height=1).pack(fill="x", padx=20, pady=14)

        tk.Label(side, text="FICHEIROS CARREGADOS", bg=self.cor_bg,
                 fg="#94a3b8", font=("Segoe UI", 8, "bold")).pack(pady=(0, 6))
        self.history_frame = tk.Frame(side, bg=self.cor_bg)
        self.history_frame.pack(fill="both", expand=True, padx=10)

        # ══════════════════════════════════════════════════════════════════════
        # PAINEL PRINCIPAL
        # ══════════════════════════════════════════════════════════════════════
        self.main_panel = tk.Frame(self.root, bg=BG)
        self.main_panel.pack(side="right", fill="both", expand=True)

        # ── Barra superior: período + abas de base ────────────────────────────
        top_bar = tk.Frame(self.main_panel, bg=WH,
                           highlightbackground="#e2e8f0", highlightthickness=1)
        top_bar.pack(fill="x", padx=20, pady=(16, 0))

        tk.Label(top_bar, text="Período:", bg=WH,
                 font=("Segoe UI", 9, "bold"), fg="#475569").pack(side="left", padx=(16, 6), pady=10)
        self.time_combo = ttk.Combobox(top_bar,
                                       values=["1 Mês","3 Meses","6 Meses","1 Ano","Tudo"],
                                       state="readonly", width=12)
        self.time_combo.set(self.time_filter)
        self.time_combo.pack(side="left", pady=10)
        self.time_combo.bind("<<ComboboxSelected>>", self.on_time_filter_change)

        # separador vertical
        tk.Frame(top_bar, bg="#e2e8f0", width=1).pack(side="left", fill="y", padx=16, pady=6)

        # Pesquisa
        tk.Label(top_bar, text="🔍", bg=WH, font=("Segoe UI", 11)).pack(side="left", padx=(0,4))
        self.combo_clientes = ttk.Combobox(top_bar, width=45, textvariable=self.search_var)
        self.combo_clientes.pack(side="left", pady=10)
        tk.Button(top_bar, text="✕", command=self.limpar_pesquisa_dashboard,
                  bg="#ef4444", fg="white", relief="flat",
                  font=("Segoe UI", 8, "bold"), width=2, cursor="hand2").pack(side="left", padx=(4, 16))

        # Dias previsão
        tk.Frame(top_bar, bg="#e2e8f0", width=1).pack(side="left", fill="y", pady=6)
        tk.Label(top_bar, text="Previsão:", bg=WH,
                 font=("Segoe UI", 9, "bold"), fg="#475569").pack(side="left", padx=(16,4))
        self.dias_previsao_var = tk.IntVar(value=10)
        ttk.Spinbox(top_bar, from_=1, to=30, textvariable=self.dias_previsao_var,
                    width=3).pack(side="left", pady=10)
        tk.Label(top_bar, text="dias", bg=WH,
                 font=("Segoe UI", 9), fg="#64748b").pack(side="left", padx=(4,8))
        tk.Button(top_bar, text="⏳ Calcular", command=self.mostrar_previsao_dias,
                  bg="#0284c7", fg="white", relief="flat",
                  font=("Segoe UI", 9, "bold"), padx=10, cursor="hand2").pack(side="left", pady=8)

        tk.Frame(top_bar, bg="#e2e8f0", width=1).pack(side="left", fill="y", padx=12, pady=6)
        tk.Button(top_bar, text="📄 Resumo", command=self.gerar_relatorio_resumo,
                  bg="#10b981", fg="white", relief="flat",
                  font=("Segoe UI", 9, "bold"), padx=10, cursor="hand2").pack(side="left", pady=8)

        self.combo_clientes.bind('<KeyRelease>',      self.handle_combo_keypress)
        self.combo_clientes.bind('<FocusIn>',  lambda e: self.combo_clientes.after(10, lambda: self.combo_clientes.selection_range(0, tk.END)))
        self.combo_clientes.bind('<Button-1>', lambda e: self.combo_clientes.after(10, lambda: self.combo_clientes.selection_range(0, tk.END)))
        self.combo_clientes.bind('<<ComboboxSelected>>', self.plotar_evolucao)
        self.combo_clientes.bind('<Return>',           self.plotar_evolucao)

        # ── Abas de base ──────────────────────────────────────────────────────
        self.tabs = ttk.Notebook(self.main_panel)
        self.tabs.pack(fill="x", padx=20, pady=(10, 0))
        self.tabs.bind("<<NotebookTabChanged>>", self.on_tab_change)
        self.tabs.add(tk.Frame(self.tabs), text="  Visão Agregada  ")
        self.tabs.add(tk.Frame(self.tabs), text="  Base 431  ")
        self.tabs.add(tk.Frame(self.tabs), text="  Base 438  ")

        # ── KPI cards — dois grupos ───────────────────────────────────────────
        kpi_wrap = tk.Frame(self.main_panel, bg=BG)
        kpi_wrap.pack(fill="x", padx=20, pady=(14, 0))

        # Grupo 1: posição atual (cards maiores, com barra colorida no topo)
        grp1 = tk.Frame(kpi_wrap, bg=BG)
        grp1.pack(side="left", fill="x", expand=True)
        tk.Label(grp1, text="POSIÇÃO ATUAL", bg=BG,
                 fg="#94a3b8", font=("Segoe UI", 7, "bold")).pack(anchor="w", padx=4, pady=(0,4))
        row1 = tk.Frame(grp1, bg=BG)
        row1.pack(fill="x")

        self.card_total     = self._kpi(row1, "Risco Total",      "R$ 0,00", "#0ea5e9", "#dbeafe", 0, grp1=True)
        self.card_vencido   = self._kpi(row1, "Vencido",          "R$ 0,00", "#dc2626", "#fee2e2", 1, grp1=True)
        self.card_a_vencer  = self._kpi(row1, "A Vencer",         "R$ 0,00", "#2563eb", "#eff6ff", 2, grp1=True)
        self.card_disponivel= self._kpi(row1, "Limite Disponível","R$ 0,00", "#059669", "#dcfce7", 3, grp1=True)

        # separador
        tk.Frame(kpi_wrap, bg="#e2e8f0", width=1).pack(side="left", fill="y", padx=12, pady=4)

        # Grupo 2: fluxo do período (cards menores)
        grp2 = tk.Frame(kpi_wrap, bg=BG)
        grp2.pack(side="left", fill="x")
        tk.Label(grp2, text="FLUXO DO PERÍODO", bg=BG,
                 fg="#94a3b8", font=("Segoe UI", 7, "bold")).pack(anchor="w", padx=4, pady=(0,4))
        row2 = tk.Frame(grp2, bg=BG)
        row2.pack(fill="x")

        self.card_aquisicao = self._kpi(row2, "Aquisição",  "R$ 0,00", "#7c3aed", "#ede9fe", 0, grp1=False)
        self.card_quitado   = self._kpi(row2, "Liquidado",  "R$ 0,00", "#16a34a", "#f0fdf4", 1, grp1=False)

        # ── Área de conteúdo: gráfico + tabela em abas ────────────────────────
        content = tk.Frame(self.main_panel, bg=BG)
        content.pack(fill="both", expand=True, padx=20, pady=(12, 12))

        # Filtros de série — linha acima do gráfico
        serie_bar = tk.Frame(content, bg=WH,
                             highlightbackground="#e2e8f0", highlightthickness=1)
        serie_bar.pack(fill="x", pady=(0, 6))

        tk.Label(serie_bar, text="Exibir no gráfico:", bg=WH,
                 font=("Segoe UI", 8, "bold"), fg="#64748b").pack(side="left", padx=(12,8), pady=6)

        self.var_show_risco    = tk.BooleanVar(value=True)
        self.var_show_vencido  = tk.BooleanVar(value=True)
        self.var_show_avencer  = tk.BooleanVar(value=True)
        self.var_show_aquisicao= tk.BooleanVar(value=True)
        self.var_show_liquidado= tk.BooleanVar(value=True)

        series = [
            ("Risco Total", self.var_show_risco,    "#0ea5e9"),
            ("Vencido",     self.var_show_vencido,  "#dc2626"),
            ("A Vencer",    self.var_show_avencer,  "#2563eb"),
            ("Aquisição",   self.var_show_aquisicao,"#7c3aed"),
            ("Liquidação",  self.var_show_liquidado,"#16a34a"),
        ]
        for label, var, cor in series:
            frm = tk.Frame(serie_bar, bg=WH)
            frm.pack(side="left", padx=6, pady=6)
            # bolinha colorida
            tk.Label(frm, text="●", bg=WH, fg=cor,
                     font=("Segoe UI", 10)).pack(side="left")
            tk.Checkbutton(frm, text=label, variable=var,
                           command=self.plotar_evolucao,
                           bg=WH, fg="#374151",
                           font=("Segoe UI", 8),
                           activebackground=WH,
                           selectcolor=WH).pack(side="left")

        # Notebook interno: Gráfico | Histórico
        self.inner_tabs = ttk.Notebook(content)
        self.inner_tabs.pack(fill="both", expand=True)

        self.chart_frame = tk.Frame(self.inner_tabs, bg=WH)
        self.inner_tabs.add(self.chart_frame, text="  📈  Evolução  ")

        hist_frame = tk.Frame(self.inner_tabs, bg=WH)
        self.inner_tabs.add(hist_frame, text="  📋  Histórico  ")

        # Tabela de histórico
        cols_tree = ("Data", "Risco Aberto", "Vencido", "A Vencer", "Aquisição", "Liquidado")
        self.tree = ttk.Treeview(hist_frame, columns=cols_tree, show="headings")
        widths    = {"Data": 110, "Risco Aberto": 160, "Vencido": 140,
                     "A Vencer": 140, "Aquisição": 140, "Liquidado": 140}
        for col in cols_tree:
            self.tree.heading(col, text=col)
            self.tree.column(col, anchor="center", width=widths.get(col, 130))

        # cores alternadas nas linhas
        self.tree.tag_configure('par',   background='#f8fafc')
        self.tree.tag_configure('impar', background='white')

        vsb = ttk.Scrollbar(hist_frame, orient="vertical",   command=self.tree.yview)
        hsb = ttk.Scrollbar(hist_frame, orient="horizontal",  command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right",  fill="y")
        hsb.pack(side="bottom", fill="x")
        self.tree.pack(fill="both", expand=True)

    def _kpi(self, parent, label, value, cor_texto, cor_bg, col, grp1=True):
        """Cria um KPI card com barra colorida no topo e retorna o label de valor."""
        w = 200 if grp1 else 170
        card = tk.Frame(parent, bg="white",
                        highlightbackground="#e2e8f0", highlightthickness=1,
                        width=w)
        card.grid(row=0, column=col, padx=4, sticky="nsew")
        card.grid_propagate(False)
        parent.grid_columnconfigure(col, weight=1)

        # barra colorida no topo
        tk.Frame(card, bg=cor_texto, height=4).pack(fill="x")

        inner = tk.Frame(card, bg="white", padx=14, pady=10)
        inner.pack(fill="both", expand=True)

        tk.Label(inner, text=label.upper(), bg="white",
                 fg="#94a3b8", font=("Segoe UI", 7, "bold")).pack(anchor="w")
        lbl = tk.Label(inner, text=value, bg="white",
                       fg=cor_texto,
                       font=("Segoe UI", 14 if grp1 else 12, "bold"))
        lbl.pack(anchor="w", pady=(4, 0))
        return lbl

    # manter compatibilidade — create_kpi_card não é mais chamado internamente
    def create_kpi_card(self, label, value, color, col):
        return self._kpi(self.kpi_cont, label, value, color, "#f8fafc", col)

    def on_time_filter_change(self, event): self.time_filter = self.time_combo.get(); self.plotar_evolucao()

    def limpar_pesquisa_dashboard(self):
        self.search_var.set("TODOS")
        self.combo_clientes['values'] = self.full_list_entidades
        self.combo_clientes.focus_set()
        self.combo_clientes.after(10, lambda: self.combo_clientes.selection_range(0, tk.END))
        self.plotar_evolucao()

    def obter_filtrados(self, pattern):
        if not pattern or pattern == "TODOS": 
            return self.full_list_entidades
        return [item for item in self.full_list_entidades if pattern in item.upper()]

    def handle_combo_keypress(self, event):
        # MELHORIA: Sem autocompletar intrusivo. Permite digitação livre do utilizador.
        try:
            if event.keysym in ('Return', 'Up', 'Down', 'Escape', 'Tab', 'Left', 'Right', 'Shift_L', 'Shift_R', 'Control_L', 'Control_R', 'Caps_Lock'):
                return
                
            text = self.search_var.get().upper()
            filtered = self.obter_filtrados(text)
            self.combo_clientes['values'] = filtered
        except tk.TclError:
            pass

    def switch_contexto(self, novo): 
        self.contexto = novo
        self.view_filter = "Agregado"
        self.setup_ui()
        self.atualizar_interface()

    def on_tab_change(self, event):
        try:
            tab_idx = self.tabs.index(self.tabs.select())
            self.view_filter = ["Agregado", "431", "438"][tab_idx]
            self.atualizar_interface()
        except tk.TclError:
            pass

    def mostrar_previsao_dias(self):
        try:
            dias = int(self.dias_previsao_var.get())
            if dias < 1: dias = 1
            if dias > 30: dias = 30
            self.dias_previsao_var.set(dias)
        except ValueError:
            dias = 10
            self.dias_previsao_var.set(10)
            
        hoje_dt = datetime.now()
        hoje_str = hoje_dt.strftime('%Y-%m-%d')
        alvo_dias_str = (hoje_dt + timedelta(days=dias)).strftime('%Y-%m-%d')
        
        sel = self.search_var.get()
        cursor = self.conn.cursor()
        
        query = f"SELECT vencimento, nome_cliente, nome_sacado, numero_titulo, saldo_titulo FROM titulos_ativos WHERE vencimento >= '{hoje_str}' AND vencimento <= '{alvo_dias_str}'"
        params = []
        
        if sel.startswith("GRUPO: "):
            nome_g = sel.replace("GRUPO: ", "")
            cursor.execute("SELECT entidade_id FROM grupos WHERE tipo=? AND nome_grupo=?", (self.contexto, nome_g))
            ids = [r[0] for r in cursor.fetchall()]
            
            if ids:
                if self.contexto == "CLIENTE":
                    query += f" AND nome_cliente IN ({','.join(['?']*len(ids))})"
                else:
                    query += f" AND cnpj_sacado IN ({','.join(['?']*len(ids))})"
                params.extend(ids)
            else:
                query += " AND 1=0"
                
        elif sel != "TODOS" and sel != "":
            ent_id_sel = sel.split(" | ")[0] if " | " in sel else sel
            cursor.execute("SELECT entidade_id, MAX(nome_entidade) FROM registros WHERE (entidade_id=? OR nome_entidade=?) AND tipo_registro=? GROUP BY entidade_id LIMIT 1", (ent_id_sel, sel, self.contexto))
            r = cursor.fetchone()
            if r:
                if self.contexto == "CLIENTE":
                    query += " AND nome_cliente = ?"
                    params.append(r[1])
                else:
                    query += " AND cnpj_sacado = ?"
                    params.append(r[0])
                    
        query += " ORDER BY vencimento ASC"
        cursor.execute(query, params)
        resultados = cursor.fetchall()
        
        win = tk.Toplevel(self.root)
        win.title(f"Previsão de Liquidação - Próximos {dias} Dias ({sel})")
        win.geometry("1050x500") 
        win.configure(bg="white")
        win.grab_set()
        
        total_liquidar = sum([r[4] for r in resultados])
        
        header_frame = tk.Frame(win, bg="#eff6ff", pady=15, padx=20, borderwidth=1, relief="solid")
        header_frame.pack(fill="x", padx=20, pady=15)
        
        tk.Label(header_frame, text=f"PREVISÃO DE ENTRADA ({dias} DIAS):", font=("Arial", 10, "bold"), bg="#eff6ff", fg="#1e3a8a").pack(side="left")
        tk.Label(header_frame, text=format_brl(total_liquidar), font=("Arial", 16, "bold"), bg="#eff6ff", fg="#2563eb").pack(side="left", padx=10)
        tk.Label(header_frame, text="(Soma dos títulos ativos que irão vencer neste período)", font=("Arial", 9, "italic"), bg="#eff6ff", fg="#64748b").pack(side="left", padx=10)
        
        tree_frame = tk.Frame(win, bg="white")
        tree_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        
        tree_prev = ttk.Treeview(tree_frame, columns=("Data Vencimento", "Faltam (Dias)", "Cliente (Cedente)", "Sacado", "Nº Título", "Valor a Liquidar"), show="headings")
        for col, width in zip(("Data Vencimento", "Faltam (Dias)", "Cliente (Cedente)", "Sacado", "Nº Título", "Valor a Liquidar"), (120, 100, 200, 250, 100, 150)):
            tree_prev.heading(col, text=col)
            tree_prev.column(col, anchor="center" if col in ["Data Vencimento", "Faltam (Dias)", "Nº Título"] else ("e" if col=="Valor a Liquidar" else "w"), width=width)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree_prev.yview)
        tree_prev.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree_prev.pack(side="left", fill="both", expand=True)
        
        hoje_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        for r in resultados:
            try: 
                venc_date = datetime.strptime(r[0], '%Y-%m-%d')
                dt_formatada = venc_date.strftime('%d/%m/%Y')
                dias_restantes = (venc_date - hoje_date).days 
            except: 
                dt_formatada = r[0]
                dias_restantes = "-"
                
            tree_prev.insert("", "end", values=(dt_formatada, dias_restantes, r[1], r[2], r[3], format_brl(r[4])))

    def gerar_relatorio_resumo(self):
        sel = self.search_var.get()
        if not sel or sel == "TODOS" or sel.startswith("GRUPO:"):
            messagebox.showwarning("Aviso", "Selecione um Cliente ou Sacado específico na pesquisa antes de gerar o Resumo.")
            return
            
        cursor = self.conn.cursor()
        
        # Limpa a pontuação do CNPJ visual para buscar corretamente o relatório
        if " | CNPJ: " in sel:
            ent_id_sel = limpar_cnpj(sel.split(" | CNPJ: ")[1])
            sel_nome = sel.split(" | CNPJ: ")[0]
        else:
            ent_id_sel = sel
            sel_nome = sel
            
        cursor.execute("SELECT entidade_id, MAX(nome_entidade) FROM registros WHERE (entidade_id=? OR nome_entidade=?) AND tipo_registro=? GROUP BY entidade_id LIMIT 1", (ent_id_sel, sel_nome, self.contexto))
        r = cursor.fetchone()
        
        if not r:
            messagebox.showwarning("Aviso", "Entidade não encontrada no histórico da base de dados.")
            return
            
        ent_id, ent_nome = r[0], r[1]
        
        cursor.execute('''
            SELECT numero_titulo, data_operacao, vencimento, data_quitacao, valor_titulo, saldo_titulo, nome_sacado, nome_cliente
            FROM titulos_completos 
            WHERE contexto=? AND entidade_id=? 
            ORDER BY vencimento ASC
        ''', (self.contexto, ent_id))
        titulos = cursor.fetchall()
        
        if not titulos:
            messagebox.showinfo("Info", "Ainda não existem títulos mapeados para esta entidade no ficheiro importado.")
            return

        contraparte_header = "Sacado" if self.contexto == "CLIENTE" else "Cliente (Cedente)"

        html = f"""
        <!DOCTYPE html>
        <html lang="pt-BR">
        <head>
            <meta charset="utf-8">
            <title>Relatório de Títulos - {ent_nome}</title>
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 30px; color: #333; }}
                .header {{ border-bottom: 2px solid #1e3a8a; padding-bottom: 15px; margin-bottom: 25px; }}
                h2 {{ color: #1e3a8a; margin: 0 0 10px 0; font-size: 24px; text-transform: uppercase; }}
                .info {{ font-size: 14px; color: #475569; margin: 4px 0; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 13px; }}
                th, td {{ border: 1px solid #cbd5e1; padding: 10px 12px; text-align: left; }}
                th {{ background-color: #f8fafc; color: #0f172a; font-weight: bold; border-bottom: 2px solid #94a3b8; }}
                tr:nth-child(even) {{ background-color: #f8fafc; }}
                .atraso {{ color: #dc2626; font-weight: bold; }}
                .adiantado {{ color: #16a34a; font-weight: bold; }}
                .aberto {{ color: #d97706; font-weight: bold; }}
                .right {{ text-align: right; }}
                .center {{ text-align: center; }}
                .totais th {{ background-color: #e2e8f0; font-size: 14px; padding-top: 15px; padding-bottom: 15px; }}
                @media print {{
                    @page {{ margin: 1cm; }}
                    body {{ margin: 0; }}
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h2>Histórico de Operações e Comportamento de Pagamento</h2>
                <p class="info"><strong>Contexto:</strong> {self.contexto}</p>
                <p class="info"><strong>Entidade:</strong> {ent_nome} (ID/CNPJ: {ent_id})</p>
                <p class="info"><strong>Emitido em:</strong> {datetime.now().strftime('%d/%m/%Y às %H:%M')}</p>
            </div>
            
            <table>
                <thead>
                    <tr>
                        <th>Nº Título</th>
                        <th>{contraparte_header}</th>
                        <th class="center">Data Operação</th>
                        <th class="center">Vencimento</th>
                        <th class="center">Data Pagamento</th>
                        <th class="right">Valor de Face</th>
                        <th class="right">Saldo Atual</th>
                        <th class="center">Diagnóstico do Pagamento</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        total_valor = 0
        total_saldo = 0
        
        for t in titulos:
            if len(t) == 8:
                n_tit, d_op, d_venc, d_quit, v_tit, s_tit, n_sacado, n_cliente = t
            else:
                n_tit, d_op, d_venc, d_quit, v_tit, s_tit = t[:6]
                n_sacado, n_cliente = "N/A", "N/A"
                
            contraparte_nome = n_sacado if self.contexto == "CLIENTE" else n_cliente
            
            total_valor += v_tit or 0
            total_saldo += s_tit or 0
            
            f_op = datetime.strptime(d_op, '%Y-%m-%d').strftime('%d/%m/%Y') if d_op and str(d_op) != 'NaT' else '-'
            f_venc = datetime.strptime(d_venc, '%Y-%m-%d').strftime('%d/%m/%Y') if d_venc and str(d_venc) != 'NaT' else '-'
            f_quit = datetime.strptime(d_quit, '%Y-%m-%d').strftime('%d/%m/%Y') if d_quit and str(d_quit) != 'NaT' else '-'
            
            status = ""
            if d_quit and str(d_quit) != 'NaT' and d_venc and str(d_venc) != 'NaT':
                v_dt = datetime.strptime(d_venc, '%Y-%m-%d')
                q_dt = datetime.strptime(d_quit, '%Y-%m-%d')
                diff = (q_dt - v_dt).days
                if diff > 0:
                    status = f"<span class='atraso'>Pago c/ {diff} dias de atraso</span>"
                elif diff < 0:
                    status = f"<span class='adiantado'>Pago {-diff} dias adiantado</span>"
                else:
                    status = "<span class='adiantado'>Pago no dia exato</span>"
            else:
                if d_venc and str(d_venc) != 'NaT':
                    v_dt = datetime.strptime(d_venc, '%Y-%m-%d')
                    hoje_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                    if hoje_dt > v_dt:
                        status = f"<span class='atraso'>Vencido há {(hoje_dt - v_dt).days} dias</span>"
                    else:
                        dias_f = (v_dt - hoje_dt).days
                        status = f"<span class='aberto'>A vencer (em {dias_f} dias)</span>"
                else:
                    status = "<span class='aberto'>Em Aberto</span>"
                    
            html += f"""
                <tr>
                    <td>{n_tit}</td>
                    <td>{contraparte_nome}</td>
                    <td class="center">{f_op}</td>
                    <td class="center">{f_venc}</td>
                    <td class="center">{f_quit}</td>
                    <td class="right">{format_brl(v_tit)}</td>
                    <td class="right">{format_brl(s_tit)}</td>
                    <td class="center">{status}</td>
                </tr>
            """
            
        html += f"""
                </tbody>
                <tfoot>
                    <tr class="totais">
                        <th colspan="5" class="right">VOLUMES TOTAIS OPERADOS:</th>
                        <th class="right">{format_brl(total_valor)}</th>
                        <th class="right">{format_brl(total_saldo)}</th>
                        <th></th>
                    </tr>
                </tfoot>
            </table>
        </body>
        </html>
        """
        
        fd, path = tempfile.mkstemp(suffix='.html', prefix='resumo_risco_')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(html)
            
        webbrowser.open('file://' + os.path.realpath(path))

    def importar_lote_dual(self):
        paths = filedialog.askopenfilenames(filetypes=[("Arquivos Excel/CSV", "*.xlsx *.xls *.csv")])
        if not paths: return
        if not messagebox.askyesno("Confirmação", "Deseja substituir os valores atuais?\n(Os limites definidos serão mantidos)"): return
        
        hoje_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cursor = self.conn.cursor()
        
        cursor.execute("DELETE FROM registros") 
        cursor.execute("DELETE FROM titulos_ativos") 
        cursor.execute("DELETE FROM titulos_completos") 
        self.conn.commit()

        erros = []
        df_list = []
        
        for path in paths:
            try:
                base_id = "431" if "431" in os.path.basename(path) else "438" if "438" in os.path.basename(path) else "Extra"
                if path.lower().endswith('.csv'): df = pd.read_csv(path, encoding='latin-1', sep=None, engine='python')
                else: df = pd.read_excel(path)
                
                df['base_id'] = base_id
                df['nome_arquivo'] = os.path.basename(path)
                df_list.append(df)
            except Exception as e:
                erros.append(f"Erro ao ler {os.path.basename(path)}: {e}")

        if not df_list:
            if erros: messagebox.showwarning("Erro", "\n".join(erros))
            return

        try:
            df_all = pd.concat(df_list, ignore_index=True)
            
            if 'CNPJ/CPF Sacado' in df_all.columns:
                df_all['CNPJ/CPF Sacado'] = df_all['CNPJ/CPF Sacado'].apply(limpar_cnpj)

            if 'Número Título' in df_all.columns and 'CNPJ/CPF Sacado' in df_all.columns:
                df_all['Número Título'] = df_all['Número Título'].astype(str).str.strip()
                df_all = df_all.drop_duplicates(subset=['CNPJ/CPF Sacado', 'Número Título'], keep='last')

            df_all['Vencimento'] = pd.to_datetime(df_all['Vencimento'], dayfirst=True, errors='coerce').dt.normalize()
            df_all['Data Operação'] = pd.to_datetime(df_all['Data Operação'], dayfirst=True, errors='coerce').dt.normalize()
            df_all['Data Quitação'] = pd.to_datetime(df_all['Data Quitação'], dayfirst=True, errors='coerce').dt.normalize()
            
            df_all['Data Quitação'] = df_all['Data Quitação'] - pd.offsets.BDay(1)
            
            df_all['Valor Título'] = pd.to_numeric(df_all['Valor Título'], errors='coerce').fillna(0.0)
            
            if 'Saldo Título' in df_all.columns:
                df_all['Saldo Título'] = pd.to_numeric(df_all['Saldo Título'], errors='coerce').fillna(0.0)
            else:
                df_all['Saldo Título'] = df_all['Valor Título']
            
            mask_ativos_hoje = (df_all['Data Operação'] <= hoje_dt) & ((df_all['Data Quitação'].isna()) | (df_all['Data Quitação'] > hoje_dt))
            df_ativos_hoje = df_all[mask_ativos_hoje]
            
            for _, row in df_ativos_hoje.iterrows():
                cliente = str(row.get('Nome Cliente', '')).strip().upper()
                sacado_cnpj = limpar_cnpj(row.get('CNPJ/CPF Sacado', ''))
                sacado_nome = str(row.get('Nome Sacado', '')).strip().upper()
                num_titulo = str(row.get('Número Título', '')).strip()
                venc = row.get('Vencimento')
                if pd.isna(venc): continue
                venc_str = venc.strftime('%Y-%m-%d')
                saldo = float(row.get('Saldo Título', 0))
                if saldo <= 0: continue
                
                cursor.execute("INSERT INTO titulos_ativos (nome_cliente, cnpj_sacado, nome_sacado, numero_titulo, vencimento, saldo_titulo) VALUES (?, ?, ?, ?, ?, ?)",
                               (cliente, sacado_cnpj, sacado_nome, num_titulo, venc_str, saldo))

            col_cnpj_cliente = next((c for c in df_all.columns if 'CNPJ' in c.upper() and 'SACADO' not in c.upper()), None)

            for ctx in ["CLIENTE", "SACADO"]:
                try:
                    if ctx == "CLIENTE":
                        col_nome = 'Nome Cliente'
                        if col_nome not in df_all.columns: continue
                        df_all[col_nome] = df_all[col_nome].astype(str).str.strip().str.upper()
                        group_cols = [col_nome]
                    else:
                        col_id = 'CNPJ/CPF Sacado'
                        col_nome = 'Nome Sacado'
                        if col_id not in df_all.columns or col_nome not in df_all.columns: continue
                        
                        df_all[col_id] = df_all[col_id].astype(str).str.strip()
                        map_nomes = df_all.groupby(col_id)[col_nome].last().to_dict()
                        df_all[col_nome] = df_all[col_id].map(map_nomes).astype(str).str.strip().str.upper()
                        
                        group_cols = [col_id, col_nome]

                    df_bd = pd.DataFrame()
                    df_bd['contexto'] = [ctx] * len(df_all)
                    if ctx == "CLIENTE":
                        df_bd['entidade_id'] = df_all[col_nome]
                        df_bd['nome_entidade'] = df_all[col_nome]
                    else:
                        df_bd['entidade_id'] = df_all[col_id].apply(limpar_cnpj)
                        df_bd['nome_entidade'] = df_all[col_nome]
                        
                    if 'Número Título' in df_all.columns:
                        df_bd['numero_titulo'] = df_all['Número Título']
                    else:
                        df_bd['numero_titulo'] = 'N/A'
                        
                    if 'Nome Cliente' in df_all.columns:
                        df_bd['nome_cliente'] = df_all['Nome Cliente'].astype(str).str.strip().str.upper()
                    else:
                        df_bd['nome_cliente'] = 'N/A'
                        
                    if 'Nome Sacado' in df_all.columns:
                        df_bd['nome_sacado'] = df_all['Nome Sacado'].astype(str).str.strip().str.upper()
                    else:
                        df_bd['nome_sacado'] = 'N/A'
                        
                    df_bd['data_operacao'] = df_all['Data Operação'].dt.strftime('%Y-%m-%d')
                    df_bd['vencimento'] = df_all['Vencimento'].dt.strftime('%Y-%m-%d')
                    df_bd['data_quitacao'] = df_all['Data Quitação'].dt.strftime('%Y-%m-%d')
                    df_bd['valor_titulo'] = df_all['Valor Título']
                    df_bd['saldo_titulo'] = df_all['Saldo Título']
                    
                    df_bd = df_bd[df_bd['entidade_id'] != '']
                    df_bd = df_bd[df_bd['entidade_id'] != 'NAN']
                    df_bd.to_sql('titulos_completos', self.conn, if_exists='append', index=False)

                    agg_meta = df_all.groupby(group_cols).agg({'base_id':'first', 'nome_arquivo':'first'}).reset_index()

                    datas_op = df_all['Data Operação'].dropna()
                    datas_qt = df_all['Data Quitação'].dropna()
                    datas_vc = df_all['Vencimento'].dropna()
                    datas_vp = datas_vc + pd.Timedelta(days=1)

                    datas_chave = pd.to_datetime(pd.concat([datas_op, datas_qt, datas_vc, datas_vp]).unique())
                    datas_chave = sorted([d for d in datas_chave if d <= hoje_dt])
                    if hoje_dt not in datas_chave: datas_chave.append(hoje_dt)
                    
                    for data_alvo in datas_chave:
                        dt_str = data_alvo.strftime('%Y-%m-%d')
                        
                        mask_ativos = (df_all['Data Operação'] <= data_alvo) & ((df_all['Data Quitação'].isna()) | (df_all['Data Quitação'] > data_alvo))
                        mask_quitados = (df_all['Data Quitação'] == data_alvo)
                        mask_aquisicoes = (df_all['Data Operação'] == data_alvo)
                        
                        df_ativos = df_all[mask_ativos].copy()
                        df_quitados = df_all[mask_quitados].copy()
                        df_aquisicoes = df_all[mask_aquisicoes].copy()
                        
                        if df_ativos.empty and df_quitados.empty and df_aquisicoes.empty: continue
                        
                        if not df_ativos.empty:
                            df_ativos['vencido'] = 0.0
                            df_ativos['a_vencer'] = 0.0
                            
                            mask_v = df_ativos['Vencimento'] < data_alvo
                            mask_a = (df_ativos['Vencimento'] >= data_alvo) | (df_ativos['Vencimento'].isna())
                            
                            df_ativos.loc[mask_v, 'vencido'] = df_ativos.loc[mask_v, 'Valor Título']
                            df_ativos.loc[mask_a, 'a_vencer'] = df_ativos.loc[mask_a, 'Valor Título']
                            
                            agg_a = df_ativos.groupby(group_cols).agg({'Valor Título':'sum', 'vencido':'sum', 'a_vencer':'sum'}).reset_index()
                        else:
                            agg_a = pd.DataFrame(columns=group_cols + ['Valor Título', 'vencido', 'a_vencer'])
                            
                        if not df_quitados.empty:
                            agg_q = df_quitados.groupby(group_cols).agg({'Valor Título':'sum'}).rename(columns={'Valor Título':'quitado'}).reset_index()
                        else:
                            agg_q = pd.DataFrame(columns=group_cols + ['quitado'])
                            
                        if not df_aquisicoes.empty:
                            agg_aq = df_aquisicoes.groupby(group_cols).agg({'Valor Título':'sum'}).rename(columns={'Valor Título':'aquisicao'}).reset_index()
                        else:
                            agg_aq = pd.DataFrame(columns=group_cols + ['aquisicao'])
                            
                        final = pd.merge(agg_a, agg_q, on=group_cols, how='outer').fillna(0.0)
                        final = pd.merge(final, agg_aq, on=group_cols, how='outer').fillna(0.0)
                        final = pd.merge(final, agg_meta, on=group_cols, how='left')
                        
                        for _, r in final.iterrows():
                            if ctx == "CLIENTE":
                                uid = str(r[col_nome]).strip()
                                nome_ent = uid
                            else:
                                uid = limpar_cnpj(r[col_id])
                                nome_ent = str(r[col_nome]).strip()
                            
                            if not uid or uid.upper() == 'NAN': continue
                            
                            cursor.execute('''INSERT INTO registros (tipo_registro, data_base, base_id, nome_arquivo, entidade_id, nome_entidade, valor_aberto, valor_vencido, valor_a_vencer, valor_quitado, valor_aquisicao) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                                          (ctx, dt_str, str(r.get('base_id', 'Unificada')), str(r.get('nome_arquivo', 'Multi')), uid, nome_ent, float(r.get('Valor Título', 0)), float(r.get('vencido', 0)), float(r.get('a_vencer', 0)), float(r.get('quitado', 0)), float(r.get('aquisicao', 0))))
                except Exception as e:
                    erros.append(f"Alerta em {ctx}: {e}")
        except Exception as e:
            erros.append(f"Erro fatal: {e}")
            
        self.conn.commit()
        if erros: messagebox.showwarning("Avisos", "Importação concluída com alguns avisos:\n\n" + "\n".join(erros[:5]))
        self.atualizar_interface()

    def importar_planilha_limites(self):
        """
        Importa limites da planilha de controle de riscos.

        Colunas obrigatórias : CLIENTE, LIMITE ATUAL
        Colunas opcionais    : NÚMERO CLIENTE

        LÓGICA DE MATCHING
        ──────────────────
        A âncora principal é sempre o NOME do cliente, pois o número pode
        estar errado no cadastro (o mesmo cliente com dois códigos distintos
        no banco — um correto e um cadastrado errado).

        Passo 1 — agrupa as linhas da planilha por nome normalizado e soma
                  os limites (clientes com duas linhas, ex: MEDNORTE 115+124).

        Passo 2 — para cada cliente da planilha, localiza no banco por:
          a) Match exato de nome (case-insensitive, sem acentos)
          b) Nome da planilha contido no nome do banco
          c) Nome do banco contido no nome da planilha (min 4 chars)

        Passo 3 — se houver NÚMERO CLIENTE na planilha e o match retornar
                  MAIS DE UM registro de banco (duplicata de cadastro), usa o
                  número como DESAMBIGUADOR: prefere o registro cujo
                  entidade_id bate com o número da planilha. Se nenhum bater,
                  aplica o limite em TODOS (cobre o caso do código errado que
                  ainda movimenta títulos).

        O limite é SEMPRE sobrescrito — a planilha é a fonte de verdade.
        """
        import unicodedata

        def normalizar(s):
            """Remove acentos e converte para upper para comparação robusta."""
            s = str(s).strip().upper()
            return ''.join(
                c for c in unicodedata.normalize('NFD', s)
                if unicodedata.category(c) != 'Mn'
            )

        path = filedialog.askopenfilename(filetypes=[("Arquivos Excel/CSV", "*.xlsx *.xls *.csv")])
        if not path: return
        try:
            df = pd.read_csv(path, encoding='latin-1', sep=None, engine='python') \
                 if path.lower().endswith('.csv') else pd.read_excel(path)

            # ── Validação mínima ──────────────────────────────────────────────
            if 'CLIENTE' not in df.columns or 'LIMITE ATUAL' not in df.columns:
                messagebox.showerror(
                    "Erro de Formato",
                    "Colunas obrigatórias não encontradas.\n\n"
                    "A planilha precisa ter: 'CLIENTE' e 'LIMITE ATUAL'.\n\n"
                    f"Colunas encontradas: {list(df.columns)}"
                )
                return

            # ── Normalizar planilha ───────────────────────────────────────────
            df['CLIENTE'] = df['CLIENTE'].astype(str).str.strip().str.upper()
            df = df[~df['CLIENTE'].isin(['RISCO TOTAL', 'NAN', '', 'NONE'])]
            df = df[df['CLIENTE'].notna()]
            df['LIMITE ATUAL'] = pd.to_numeric(df['LIMITE ATUAL'], errors='coerce')

            # Detectar coluna de número de cliente (aceita com ou sem acento)
            col_num = next(
                (c for c in df.columns if normalizar(c) == 'NUMERO CLIENTE'),
                None
            )
            if col_num:
                df[col_num] = pd.to_numeric(df[col_num], errors='coerce')

            # ── Passo 1: agrupa por nome, soma limites ────────────────────────
            # Guarda também o número canônico (o da linha com maior limite,
            # que tende a ser o registro principal quando há duas linhas).
            limites_planilha = {}   # nome_norm → {'limite': float, 'num': int|None}

            for _, row in df.iterrows():
                nome_p  = str(row['CLIENTE']).strip().upper()
                nome_n  = normalizar(nome_p)
                limite_v = row['LIMITE ATUAL']
                if pd.isna(limite_v) or limite_v <= 0:
                    continue
                num_v = int(row[col_num]) if col_num and pd.notna(row[col_num]) else None

                if nome_n not in limites_planilha:
                    limites_planilha[nome_n] = {'limite': 0.0, 'num': num_v, 'nome_orig': nome_p}

                limites_planilha[nome_n]['limite'] += float(limite_v)

                # Mantém o número da linha com maior limite como referência
                if num_v is not None:
                    prev_lim = limites_planilha[nome_n]['limite'] - float(limite_v)
                    if float(limite_v) >= prev_lim:
                        limites_planilha[nome_n]['num'] = num_v

            # ── Passo 2: carrega entidades do banco ───────────────────────────
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT entidade_id, MAX(nome_entidade) as nome "
                "FROM registros WHERE tipo_registro='CLIENTE' GROUP BY entidade_id"
            )
            # entidades_banco: lista de (entidade_id_str, nome_entidade_str)
            entidades_banco = [
                (str(eid).strip(), str(enome).strip())
                for eid, enome in cursor.fetchall()
            ]

            count_atualizados = 0
            nao_encontrados   = []
            log_aplicados     = []   # para debug/transparência

            for nome_n, info in limites_planilha.items():
                limite_v  = info['limite']
                num_canon = info['num']          # número "correto" da planilha
                nome_orig = info['nome_orig']

                # ── Estratégia de match (nome) ────────────────────────────────
                candidatos = [
                    (eid, enome) for eid, enome in entidades_banco
                    if normalizar(enome) == nome_n
                ]
                if not candidatos:
                    candidatos = [
                        (eid, enome) for eid, enome in entidades_banco
                        if nome_n in normalizar(enome)
                    ]
                if not candidatos:
                    candidatos = [
                        (eid, enome) for eid, enome in entidades_banco
                        if normalizar(enome) in nome_n and len(normalizar(enome)) >= 4
                    ]

                if not candidatos:
                    nao_encontrados.append(nome_orig)
                    continue

                # ── Passo 3: desambiguação por número ────────────────────────
                # Se chegou mais de um registro (duplicata de cadastro) E temos
                # o número canônico da planilha, preferimos o que bate.
                alvos = candidatos   # default: aplica em todos

                if len(candidatos) > 1 and num_canon is not None:
                    # Tenta achar o registro cujo entidade_id == número canônico
                    por_numero = [
                        (eid, enome) for eid, enome in candidatos
                        if str(eid) == str(num_canon)
                    ]
                    if por_numero:
                        # Encontrou o registro correto — aplica só nele
                        alvos = por_numero
                    # Se não achou (nenhum dos duplicados tem o número certo),
                    # mantém alvos = candidatos (aplica em todos — situação
                    # rara onde ambos os códigos têm histórico ativo)

                for eid, enome in alvos:
                    cursor.execute(
                        "INSERT OR REPLACE INTO limites (tipo, entidade_nome, valor) "
                        "VALUES ('CLIENTE', ?, ?)",
                        (enome, limite_v)
                    )
                    count_atualizados += 1
                    log_aplicados.append(
                        f"  • [{eid}] {enome} → {format_brl(limite_v)}"
                        + (" (de {})".format(', '.join(str(c[0]) for c in candidatos if c != (eid, enome)))
                           if len(candidatos) > 1 else "")
                    )

            self.conn.commit()

            # ── Mensagem de resultado ─────────────────────────────────────────
            msg = f"✅ {count_atualizados} limite(s) gravado(s).\n"
            if log_aplicados:
                msg += "\nAplicados:\n" + "\n".join(log_aplicados[:20])
                if len(log_aplicados) > 20:
                    msg += f"\n  ... e mais {len(log_aplicados)-20}."

            if nao_encontrados:
                msg += (
                    f"\n\n⚠️ {len(nao_encontrados)} cliente(s) da planilha sem correspondência "
                    f"no banco (sem carteira importada ainda):\n"
                    + "\n".join(f"  • {n}" for n in nao_encontrados[:15])
                )
                if len(nao_encontrados) > 15:
                    msg += f"\n  ... e mais {len(nao_encontrados)-15}."

            messagebox.showinfo("Importação de Limites", msg)
            self.atualizar_interface()

        except Exception as e:
            messagebox.showerror("Erro de Leitura", f"Falha ao processar planilha:\n{e}")

    def janela_gestao_entidades(self):
        win = tk.Toplevel(self.root); win.title(f"Gestão de Limites e Grupos - {self.contexto}"); win.state('zoomed'); win.grab_set()
        tabs = ttk.Notebook(win); tabs.pack(fill="both", expand=True, padx=10, pady=10)
        
        t_indiv = tk.Frame(tabs, bg="white"); tabs.add(t_indiv, text=" Registo de Limites Individuais ")
        f_top = tk.Frame(t_indiv, bg="white", pady=10); f_top.pack(fill="x", padx=20); tk.Label(f_top, text="Filtrar Nome/CNPJ:", bg="white").pack(side="left")
        
        search = tk.Entry(f_top, width=40)
        search.pack(side="left", padx=(10, 5))
        
        def limpar_gestao():
            search.delete(0, tk.END)
            carregar()
            search.focus_set()
            
        tk.Button(f_top, text="X", command=limpar_gestao, bg="#ef4444", fg="white", relief="flat", font=("Arial", 9, "bold"), width=3).pack(side="left")
        search.bind("<FocusIn>", lambda e: search.after(10, lambda: search.selection_range(0, tk.END)))
        search.bind("<Button-1>", lambda e: search.after(10, lambda: search.selection_range(0, tk.END)))

        tree = ttk.Treeview(t_indiv, columns=("ID", "Nome", "Risco Aberto", "Limite", "Disponível"), show="headings")
        for col in ("ID", "Nome", "Risco Aberto", "Limite", "Disponível"): tree.heading(col, text=col); tree.column(col, anchor="center")
        tree.column("Nome", width=350, anchor="w"); tree.pack(fill="both", expand=True, padx=20, pady=10)

        def carregar(*args):
            tree.delete(*tree.get_children()); p = search.get().upper(); cursor = self.conn.cursor()
            cursor.execute('''
                SELECT T.entidade_id, T.nome_oficial, 
                       (SELECT SUM(valor_aberto) FROM registros WHERE entidade_id = T.entidade_id AND data_base = (SELECT MAX(data_base) FROM registros)) as risco, 
                       (SELECT valor FROM limites WHERE tipo = ? AND entidade_nome = T.nome_oficial) as limite 
                FROM (
                    SELECT entidade_id, MAX(nome_entidade) as nome_oficial 
                    FROM registros 
                    WHERE tipo_registro = ? 
                    GROUP BY entidade_id
                ) T 
                ORDER BY T.nome_oficial ASC
            ''', (self.contexto, self.contexto))
            for i, n, r, l in cursor.fetchall():
                if p in str(n).upper() or p in str(i): r=r or 0; l=l or 0; tree.insert("", "end", values=(i, n, format_brl(r), format_brl(l), format_brl(l-r)))
        search.bind("<KeyRelease>", carregar); carregar()

        def edit(event=None):
            sel = tree.selection()
            if not sel: return
            item = tree.item(sel[0]); nome = item['values'][1]; v_str = str(item['values'][3]).replace('R$', '').replace('.', '').replace(',', '.').strip()
            d = CurrencyInputDialog(win, "Limite", f"Definir limite para:\n{nome}", initial_value=float(v_str) if v_str else 0.0)
            if d.result is not None: self.conn.cursor().execute("INSERT OR REPLACE INTO limites VALUES (?, ?, ?)", (self.contexto, nome, d.result)); self.conn.commit(); carregar(); self.atualizar_interface()
        tk.Button(t_indiv, text="✏️ Editar Limite", command=edit, bg="#2563eb", fg="white", pady=8).pack(pady=10); tree.bind("<Double-1>", edit)

        t_grps = tk.Frame(tabs, bg="white"); tabs.add(t_grps, text=" Grupos Económicos ")
        f_split = tk.PanedWindow(t_grps, orient="horizontal", bg="#e2e8f0"); f_split.pack(fill="both", expand=True)
        f_left = tk.Frame(f_split, bg="#f8fafc", width=250); f_split.add(f_left); tk.Label(f_left, text="GRUPOS", bg="#f8fafc", font=("Arial", 9, "bold")).pack(pady=10); lb_grps = tk.Listbox(f_left, borderwidth=0, bg="#f8fafc"); lb_grps.pack(fill="both", expand=True, padx=5)
        f_right = tk.Frame(f_split, bg="white"); f_split.add(f_right); f_grp_header = tk.Frame(f_right, bg="white", pady=10); f_grp_header.pack(fill="x", padx=20); lbl_grp_nome = tk.Label(f_grp_header, text="Selecione...", font=("Arial", 11, "bold"), bg="white"); lbl_grp_nome.pack(side="left")
        def ref(): lb_grps.delete(0, tk.END); cursor = self.conn.cursor(); cursor.execute("SELECT DISTINCT nome_grupo FROM grupos WHERE tipo = ? ORDER BY nome_grupo ASC", (self.contexto,)); [lb_grps.insert(tk.END, r[0]) for r in cursor.fetchall()]
        ref()
        
        f_gl = tk.Frame(f_right, bg="#f1f5f9", pady=10, padx=15, borderwidth=1, relief="solid"); f_gl.pack(fill="x", padx=20, pady=5); tk.Label(f_gl, text="Limite do Grupo:", bg="#f1f5f9", font=("Arial", 9, "bold")).pack(side="left"); lbl_gl = tk.Label(f_gl, text="R$ 0,00", bg="#f1f5f9", font=("Arial", 10, "bold"), fg="#2563eb"); lbl_gl.pack(side="left", padx=10)
        
        buck = tk.Frame(f_right, bg="white"); buck.pack(fill="both", expand=True, padx=20, pady=10); fbl = tk.LabelFrame(buck, text="Disponíveis", bg="white"); fbl.pack(side="left", fill="both", expand=True); lbl = tk.Listbox(fbl, selectmode="extended"); lbl.pack(fill="both", expand=True); fbb = tk.Frame(buck, bg="white"); fbb.pack(side="left", padx=5); fbr = tk.LabelFrame(buck, text="Membros do Grupo", bg="white"); fbr.pack(side="left", fill="both", expand=True); lbr = tk.Listbox(fbr, selectmode="extended"); lbr.pack(fill="both", expand=True)

        def load_buck(n):
            lbl.delete(0, tk.END); lbr.delete(0, tk.END); cursor = self.conn.cursor()
            cursor.execute('''SELECT SUM(l.valor) FROM limites l WHERE l.tipo = ? AND l.entidade_nome IN (SELECT MAX(nome_entidade) FROM registros r JOIN grupos g ON r.entidade_id = g.entidade_id WHERE g.nome_grupo = ? AND g.tipo = ? GROUP BY r.entidade_id)''', (self.contexto, n, self.contexto))
            res_sum = cursor.fetchone(); lbl_gl.config(text=format_brl(res_sum[0] if res_sum else 0))
            cursor.execute("SELECT DISTINCT r.entidade_id, r.nome_entidade FROM grupos g JOIN registros r ON g.entidade_id = r.entidade_id WHERE g.tipo=? AND g.nome_grupo=? ORDER BY r.nome_entidade ASC", (self.contexto, n)); [lbr.insert(tk.END, f"{r[0]} | {r[1]}") for r in cursor.fetchall()]
            cursor.execute("SELECT DISTINCT entidade_id, nome_entidade FROM registros WHERE tipo_registro=? AND entidade_id NOT IN (SELECT entidade_id FROM grupos WHERE tipo=?) ORDER BY nome_entidade ASC", (self.contexto, self.contexto)); [lbl.insert(tk.END, f"{r[0]} | {r[1]}") for r in cursor.fetchall()]

        def on_s(e):
            if lb_grps.curselection(): n = lb_grps.get(lb_grps.curselection()[0]); lbl_grp_nome.config(text=n); load_buck(n)
        lb_grps.bind("<<ListboxSelect>>", on_s)
        def vinc():
            n = lbl_grp_nome.cget("text")
            if "..." in n: return
            for i in lbl.curselection(): eid = lbl.get(i).split(" | ")[0]; self.conn.cursor().execute("INSERT OR REPLACE INTO grupos VALUES (?, ?, ?)", (self.contexto, eid, n))
            self.conn.commit(); load_buck(n); self.atualizar_interface()
        def desvinc():
            n = lbl_grp_nome.cget("text")
            for i in lbr.curselection(): eid = lbr.get(i).split(" | ")[0]; self.conn.cursor().execute("DELETE FROM grupos WHERE tipo=? AND nome_grupo=? AND entidade_id=?", (self.contexto, n, eid))
            self.conn.commit(); load_buck(n); self.atualizar_interface()
        tk.Button(fbb, text="Vincular >>", command=vinc, width=12, bg="#2563eb", fg="white").pack(pady=5); tk.Button(fbb, text="<< Remover", command=desvinc, width=12).pack(pady=5)
        fbt = tk.Frame(f_left, bg="#f8fafc", pady=10); fbt.pack(fill="x")
        def add_g():
            n = simpledialog.askstring("Novo", "Nome do Grupo:").upper()
            if n: self.conn.cursor().execute("INSERT OR REPLACE INTO grupos (tipo, entidade_id, nome_grupo) VALUES (?, '0', ?)", (self.contexto, n)); self.conn.commit(); ref()
        def del_g():
            if lb_grps.curselection():
                n = lb_grps.get(lb_grps.curselection()[0])
                if messagebox.askyesno("Excluir", f"Apagar grupo {n}?"): self.conn.cursor().execute("DELETE FROM grupos WHERE tipo=? AND nome_grupo=?", (self.contexto, n)); self.conn.commit(); ref(); self.atualizar_interface()
        tk.Button(fbt, text="+ Novo", command=add_g, width=8).pack(side="left", padx=5); tk.Button(fbt, text="- Apagar", command=del_g, width=8).pack(side="left")

    def atualizar_interface(self):
        cursor = self.conn.cursor(); [w.destroy() for w in self.history_frame.winfo_children()]
        cursor.execute("SELECT DISTINCT nome_arquivo, base_id FROM registros WHERE tipo_registro=? GROUP BY nome_arquivo", (self.contexto,))
        for a, b in cursor.fetchall():
            f = tk.Frame(self.history_frame, bg=self.cor_bg, pady=2); f.pack(fill="x")
            tk.Label(f, text=f"[{b}] {a[:22]}", bg=self.cor_bg, fg="#94a3b8",
                     font=("Segoe UI", 7)).pack(side="left", padx=5)
        
        try: prev = self.search_var.get()
        except: prev = "TODOS"

        cursor.execute(f"SELECT entidade_id, MAX(nome_entidade) FROM registros WHERE tipo_registro=? GROUP BY entidade_id ORDER BY MAX(nome_entidade) ASC", (self.contexto,))
        
        # AGORA, OS SACADOS EXIBEM O CNPJ NA LISTA E NÃO SE REPETEM!
        if self.contexto == "SACADO":
            clis = sorted(list(set([f"{r[0]} | {r[1]}" for r in cursor.fetchall() if r[1]])))
        else:
            clis = sorted(list(set([f"{r[1]}" for r in cursor.fetchall() if r[1]])))
        
        cursor.execute("SELECT DISTINCT nome_grupo FROM grupos WHERE tipo=? AND entidade_id != '0' ORDER BY nome_grupo ASC", (self.contexto,))
        grps = sorted(list(set([f"GRUPO: {r[0]}" for r in cursor.fetchall()])))
        
        self.full_list_entidades = ["TODOS"] + grps + clis
        
        try:
            self.combo_clientes['values'] = self.full_list_entidades
            self.search_var.set(prev if prev in self.full_list_entidades else "TODOS")
        except tk.TclError: pass
            
        self.plotar_evolucao()

    def plotar_evolucao(self, event=None):
        try: sel = self.search_var.get()
        except: return

        if sel not in self.full_list_entidades and sel != "" and sel != "TODOS":
            matches = [i for i in self.full_list_entidades if sel.upper() in i.upper()]; self.search_var.set(matches[0] if matches else "TODOS"); sel = self.search_var.get()
        
        corte = (datetime.now() - timedelta(days={"1 Mês":30,"3 Meses":90,"6 Meses":180,"1 Ano":365}.get(self.time_filter, 40000))).strftime('%Y-%m-%d')
        ids = []; limite = 0.0
        
        if sel.startswith("GRUPO: "):
            nome_g = sel.replace("GRUPO: ", ""); cursor = self.conn.cursor()
            cursor.execute("SELECT entidade_id FROM grupos WHERE tipo=? AND nome_grupo=?", (self.contexto, nome_g)); ids = [r[0] for r in cursor.fetchall()]
            cursor.execute('''SELECT SUM(l.valor) FROM limites l WHERE l.tipo = ? AND l.entidade_nome IN (SELECT MAX(nome_entidade) FROM registros r JOIN grupos g ON r.entidade_id = g.entidade_id WHERE g.nome_grupo = ? AND g.tipo = ? GROUP BY r.entidade_id)''', (self.contexto, nome_g, self.contexto))
            res_l = cursor.fetchone(); limite = res_l[0] if res_l and res_l[0] else 0.0
        elif sel != "TODOS" and sel != "":
            # INTELIGÊNCIA: Se a string tiver CNPJ, a gente separa e busca pelo CNPJ ou pelo nome
            ent_id_sel = sel.split(" | ")[0] if " | " in sel else sel
            cursor = self.conn.cursor()
            cursor.execute("SELECT entidade_id, MAX(nome_entidade) FROM registros WHERE (entidade_id=? OR nome_entidade=?) AND tipo_registro=? GROUP BY entidade_id LIMIT 1", (ent_id_sel, sel, self.contexto))
            r = cursor.fetchone()
            if r: 
                ids = [r[0]]; cursor.execute("SELECT valor FROM limites WHERE tipo=? AND entidade_nome=?", (self.contexto, r[1]))
                res_l = cursor.fetchone(); limite = res_l[0] if res_l else 0.0
        
        q = f"SELECT data_base, SUM(valor_aberto) as aberto, SUM(valor_vencido) as vencido, SUM(valor_a_vencer) as a_vencer, SUM(valor_quitado) as quitado, SUM(valor_aquisicao) as aquisicao FROM registros WHERE tipo_registro='{self.contexto}' AND data_base >= '{corte}'"
        if self.view_filter != "Agregado": q += f" AND base_id='{self.view_filter}'"
        if ids: q += f" AND entidade_id IN ({','.join(['?']*len(ids))})"
        q += " GROUP BY data_base ORDER BY data_base DESC"; df = pd.read_sql(q, self.conn, params=ids).fillna(0.0)
        
        for i in self.tree.get_children(): self.tree.delete(i)
        for idx, (_, r) in enumerate(df.iterrows()):
            try: dt = datetime.strptime(r['data_base'], '%Y-%m-%d').strftime('%d/%m/%Y')
            except: dt = r['data_base']
            tag = 'par' if idx % 2 == 0 else 'impar'
            self.tree.insert("", "end", tag=tag,
                             values=(dt, format_brl(r['aberto']), format_brl(r['vencido']),
                                     format_brl(r['a_vencer']), format_brl(r['aquisicao']),
                                     format_brl(r['quitado'])))
        
        risco = df.iloc[0]['aberto'] if not df.empty else 0
        venc = df.iloc[0]['vencido'] if not df.empty else 0
        a_venc = df.iloc[0]['a_vencer'] if not df.empty else 0
        quitado = df['quitado'].sum() if not df.empty else 0
        aquisicao = df['aquisicao'].sum() if not df.empty else 0 
        
        self.card_total.config(text=format_brl(risco))
        self.card_vencido.config(text=format_brl(venc))
        self.card_a_vencer.config(text=format_brl(a_venc))
        self.card_aquisicao.config(text=format_brl(aquisicao))
        self.card_quitado.config(text=format_brl(quitado))
        
        if limite > 0: self.card_disponivel.config(text=format_brl(limite-risco), fg="#16a34a" if (limite-risco) > 0 else "#dc2626")
        else: self.card_disponivel.config(text="Não Definido", fg="#64748b")
        
        for w in self.chart_frame.winfo_children(): w.destroy()
        if df.empty: return

        dfc = df.sort_values('data_base')
        dfc['dt'] = pd.to_datetime(dfc['data_base'])
        plt.close('all')

        fig, ax = plt.subplots(figsize=(12, 5), dpi=100)
        fig.patch.set_facecolor('white')
        ax.set_facecolor('#fafafa')

        if self.var_show_risco.get():
            ax.plot(dfc['dt'], dfc['aberto'], color='#0ea5e9',
                    label='Risco Total', linewidth=2.5, zorder=4)
            ax.fill_between(dfc['dt'], 0, dfc['aberto'],
                            color='#0ea5e9', alpha=0.06, zorder=1)

        if self.var_show_vencido.get():
            ax.fill_between(dfc['dt'], 0, dfc['vencido'],
                            color='#ef4444', alpha=0.18, label='Vencido', zorder=2)
            ax.plot(dfc['dt'], dfc['vencido'],
                    color='#ef4444', linewidth=1.8, zorder=3)

        if self.var_show_avencer.get():
            ax.plot(dfc['dt'], dfc['a_vencer'], color='#2563eb',
                    label='A Vencer', linestyle='--', linewidth=1.8, zorder=4)

        if self.var_show_aquisicao.get():
            ax.plot(dfc['dt'], dfc['aquisicao'], color='#7c3aed',
                    label='Aquisição', linewidth=1.5, linestyle='-.',
                    marker='o', markersize=3.5, zorder=5)

        if self.var_show_liquidado.get():
            ax.bar(dfc['dt'], dfc['quitado'], color='#16a34a',
                   alpha=0.35, label='Liquidação', zorder=1,
                   width=1.5)

        if limite > 0:
            ax.axhline(y=limite, color='#f59e0b', linestyle=':',
                       label=f'Limite ({format_brl(limite)})',
                       linewidth=1.8, zorder=6)

        ax.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda x, p:
                f'R$ {int(x/1000)}k' if x < 1e6 else f'R$ {x/1e6:.1f}M'))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m/%y'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.xticks(rotation=25, ha='right', fontsize=8)
        plt.yticks(fontsize=8)

        ax.grid(True, linestyle='--', alpha=0.25, color='#94a3b8')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#e2e8f0')
        ax.spines['bottom'].set_color('#e2e8f0')

        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(loc='upper left', fontsize=8, ncol=3,
                      framealpha=0.9, edgecolor='#e2e8f0')

        plt.tight_layout(pad=1.5)
        canvas = FigureCanvasTkAgg(fig, master=self.chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

if __name__ == "__main__":
    root = tk.Tk(); RiskApp(root); root.mainloop()
