# TAPRA-2026

### Equipe
* Lucas Quinaglia
* Pedro Santos
* Phelipi Moser
* Vitor Albano

---

## Listagem de Indicadores do Projeto

### 1. Total de Chamados Registrados
* **Tabela de origem:** `chamado`
* **Descrição:** Volume total de solicitações de suporte abertas no sistema.

### 2. Chamados Abertos por Mês / Período
* **Tabela de origem:** `chamado` (utilizando a coluna `dt_criacao`)
* **Descrição:** Tendência temporal do volume de chamados recebidos ao longo dos meses.

### 3. Chamados por Analista
* **Tabelas de origem:** `chamado` e `analista` (`id_analista_atual`)
* **Descrição:** Quantidade de chamados atribuídos ou resolvidos por cada membro da equipe de suporte (`nm_analista`).

### 4. Chamados por Categoria de Problema
* **Tabelas de origem:** `chamado` e `categoria` (`id_categoria`)
* **Descrição:** Distribuição dos incidentes por áreas de atendimento.

### 5. Cumprimento de Acordo de Nível de Serviço (SLA)
* **Tabelas de origem:** `chamado` e `sla`
* **Descrição:** Percentual de chamados atendidos e resolvidos dentro das metas de tempo estabelecidas.

### 6. Volume de Chamados por Fila de Atendimento
* **Tabelas de origem:** `chamado` e `fila` (`id_fila_atual`)
* **Descrição:** Quantidade de chamados distribuídos em cada departamento ou fila de suporte.

### 7. Satisfação do Cliente (CSAT)
* **Tabela de origem:** `csat`
* **Descrição:** Média de avaliação dos usuários em relação aos atendimentos encerrados.

### 8. Chamados por Status
* **Tabela de origem:** `chamado` (`ds_status_chamado`)
* **Descrição:** Panorama atual dos registros divididos por status (ex: abertos, em progresso, resolvidos).
