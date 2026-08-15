# Análise de Risco de Crédito

Painel desktop em Python para acompanhamento de exposição de crédito ao longo do tempo, voltado para operações de factoring/securitização de recebíveis.

## Funcionalidades

- **Dois contextos de análise**: acompanhamento por cliente (cedente) ou por sacado (devedor final).
- **Visão agregada ou por carteira**, com filtro de período (1 mês, 3 meses, 6 meses, 1 ano ou histórico completo).
- **Agrupamento de entidades**: permite reunir empresas relacionadas (ex: matriz/filial, empresas do mesmo grupo econômico) em um único grupo de risco, com limite de crédito compartilhado.
- **Gráfico de evolução temporal** (matplotlib) mostrando risco total, valores vencidos, a vencer, adquiridos e quitados — com opção de ativar/desativar cada série.
- **Cálculo de limite disponível**: compara o risco atual em aberto contra o limite de crédito cadastrado para cada cliente ou grupo.
- **Persistência local em SQLite**, sem dependência de servidor externo.
- **Interface gráfica** construída com Tkinter, com busca/filtro dinâmico por nome.

## Dependências

```bash
pip install pandas matplotlib
```

(`sqlite3` e `tkinter` já vêm na biblioteca padrão do Python.)

## Como usar

```bash
python RISCO.py
```

Na primeira execução, o programa cria automaticamente o banco de dados local (`banco_risco.db`) com a estrutura de tabelas necessária. Os dados de entrada (histórico de valores em aberto, vencidos, quitados etc.) são inseridos via importação de relatórios — a lógica de importação pode ser adaptada para qualquer sistema de origem que exporte esse tipo de dado.

## Observação

O projeto foi construído para uma operação real de factoring, mas a lógica de agrupamento de entidades, cálculo de limite disponível e visualização temporal de exposição de risco é genérica e se aplica a qualquer negócio que precise monitorar limites de crédito por cliente ao longo do tempo.
