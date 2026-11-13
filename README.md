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

## Sincronização diária para o banco destino

A função `sync_bronze_to_target_db` roda diariamente às 02:00 UTC. Ela lê o snapshot JSON mais recente de cada entidade em `bronze/itsm`, aplica os registros nas tabelas correspondentes do schema `itsm` e usa as chaves primárias do destino para inserir ou atualizar sem duplicar registros. As tabelas são processadas na ordem definida pelas chaves estrangeiras do banco destino.

No Azure Portal, abra a Function App correta e acesse **Settings > Environment variables > App settings**. Adicione estas configurações para o banco destino; elas são independentes das variáveis de origem `HOST`, `DATABASE`, `USER` e `PASSWORD`:

| Nome | Valor |
| --- | --- |
| `TARGET_SQL_HOST` | Host do servidor SQL destino, sem `tcp:` e sem a porta |
| `TARGET_SQL_DATABASE` | Nome do banco de dados destino |
| `TARGET_SQL_USER` | Usuário SQL autorizado no banco destino |
| `TARGET_SQL_PASSWORD` | Senha desse usuário |

Salve as configurações para reiniciar a Function App. Não coloque credenciais no código nem no repositório. O banco destino deve ter as tabelas no schema `itsm`, com chave primária, e as relações entre elas devem permitir a ordenação por chaves estrangeiras usada pela carga.
