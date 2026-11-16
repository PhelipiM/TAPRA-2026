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
* **Tabela de origem:** `csat_avaliacao` (avaliações CSAT)
* **Descrição:** Média de avaliação dos usuários em relação aos atendimentos encerrados.

### 8. Chamados por Status
* **Tabela de origem:** `chamado` (`ds_status_chamado`)
* **Descrição:** Panorama atual dos registros divididos por status (ex: abertos, em progresso, resolvidos).

## Guia de configuração e sincronização no Azure

Este guia descreve a configuração da Function App, dos bancos SQL e do Data Lake, como executar uma carga inicial e como verificar a sincronização diária. Os nomes das configurações são sensíveis a maiúsculas/minúsculas: use-os exatamente como escritos.

### 1. O que a aplicação faz

As funções `extract_*` consultam as tabelas de origem no SQL a cada minuto e gravam snapshots JSON no filesystem `bronze` do Data Lake, em caminhos como `itsm/analistas/ano=AAAA/mes=MM/dia=DD/`. O código extrai estas entidades:

| Pasta/entidade no Data Lake | Tabela SQL |
| --- | --- |
| `chamados` | `itsm.chamado` |
| `analistas` | `itsm.analista` |
| `categorias` | `itsm.categoria` |
| `chamados_sla` | `itsm.chamado_sla` |
| `chamados_status_historico` | `itsm.chamado_status_historico` |
| `clientes_organizacao` | `itsm.cliente_organizacao` |
| `csat_avaliacoes` | `itsm.csat_avaliacao` |
| `filas` | `itsm.fila` |
| `slas` | `itsm.sla` |
| `solicitantes` | `itsm.solicitante` |

A carga de destino lê o snapshot JSON mais recente de cada entidade e faz **upsert** usando as chaves primárias: insere registros ausentes e atualiza os que já existem, sem duplicá-los. Ela não apaga do destino registros removidos da origem nem mantém histórico de versões. A carga diária está programada para **02:00 UTC (23:00 no horário de Brasília)**.

### 2. Onde cadastrar as configurações

No Azure Portal, abra a Function App criada para o projeto e navegue até **Configurações > Variáveis de ambiente > Configurações de aplicativo** (*Settings > Environment variables > App settings*). Use **Adicionar** para cada configuração que estiver faltando. Depois de alterar os valores, clique em **Aplicar/Salvar** e confirme o reinício da Function App. Cada equipe deve selecionar os próprios recursos e grupo de recursos; este guia não depende de nomes específicos de grupo ou de recursos.

Esses valores devem ser cadastrados na **Function App**, não no banco SQL, no container do Data Lake nem no código-fonte. Configurações com credenciais são segredos: não as coloque no Git, README, prints ou mensagens.

### 3. Configurações da origem SQL

As funções `extract_*` usam estas quatro configurações para conectar ao banco que contém as tabelas de origem:

| Nome exato | Onde encontrar o valor |
| --- | --- |
| `HOST` | No recurso **SQL Server** de origem, abra **Visão geral** e copie o nome DNS do servidor, no formato `<servidor>.database.windows.net`. Não inclua `tcp:` nem `,1433`. |
| `DATABASE` | No recurso **SQL Database** de origem, copie o nome do banco de dados de origem. |
| `USER` | Login SQL autorizado a consultar as tabelas de origem. Não é o e-mail usado para entrar no Azure. |
| `PASSWORD` | Senha desse login SQL. O Azure não permite visualizar uma senha já cadastrada; redefina-a no servidor ou peça ao administrador para criar um login SQL. |

O login de origem precisa conseguir executar `SELECT` nas tabelas do schema `itsm` listadas acima. Se o servidor estiver com **Microsoft Entra-only authentication**, a autenticação SQL com usuário/senha não funcionará. Para este método, o servidor precisa permitir autenticação SQL (modo misto), e a senha precisa corresponder ao login.

Se precisar criar um login SQL, conecte-se ao banco `master` com o administrador do servidor e execute um comando como o abaixo, substituindo o nome e usando uma senha forte:

```sql
CREATE LOGIN [sync_login] WITH PASSWORD = '<senha-forte>';
```

Depois, conecte-se ao banco de origem e crie o usuário desse login no banco. Execute uma vez por banco:

```sql
CREATE USER [sync_login] FOR LOGIN [sync_login];
GRANT SELECT ON SCHEMA::itsm TO [sync_login];
```

### 4. Configuração do Data Lake

O código usa uma connection string para gravar e ler os snapshots. Cadastre:

| Nome exato | Onde encontrar o valor |
| --- | --- |
| `DATALAKE_CONNECTION_STRING` | No recurso **Storage account** usado pelo projeto, abra **Segurança + rede > Chaves de acesso** (*Security + networking > Access keys*) e copie a **Connection string** da chave. Não copie apenas o nome da conta ou a chave isolada. |

O container/filesystem chamado `bronze` precisa existir. A connection string tem acesso por chave à conta de armazenamento; trate-a como senha. Se uma chave ou connection string for exposta, regenere-a em **Chaves de acesso** e atualize essa configuração na Function App.

### 5. Configurações do SQL de destino

As variáveis `TARGET_SQL_*` são separadas das variáveis de origem, mesmo quando origem e destino estão no mesmo servidor ou banco. O código de sincronização usa:

| Nome exato | Onde encontrar o valor |
| --- | --- |
| `TARGET_SQL_HOST` | Em **SQL Server > Visão geral**, copie o nome DNS do servidor, no formato `<servidor>.database.windows.net`. Sem `tcp:` e sem a porta. |
| `TARGET_SQL_DATABASE` | Nome do SQL Database que receberá a carga. |
| `TARGET_SQL_USER` | Login SQL que tem permissões no banco de destino. Não é o e-mail do Azure. |
| `TARGET_SQL_PASSWORD` | Senha desse login SQL. Se não souber a senha, redefina-a ou peça ao administrador para criar outro login; não é possível recuperar a senha em texto. |

O servidor de destino precisa permitir autenticação SQL. Se **Microsoft Entra-only authentication** estiver ligado, desative essa opção no recurso **SQL Server** para permitir o modo misto. Isso não desativa o Microsoft Entra; apenas permite também logins SQL.

O banco de destino deve conter as dez tabelas do mapeamento acima no schema `itsm`, cada uma com chave primária. As chaves estrangeiras precisam permitir a ordenação das tabelas usada pela carga. O login de destino precisa de leitura de metadados e permissões `SELECT`, `INSERT` e `UPDATE` nas tabelas. Se houver colunas `IDENTITY` que precisem preservar seus valores de origem, o login também precisa da permissão necessária para executar `SET IDENTITY_INSERT`.

No banco de destino, crie o usuário correspondente ao login SQL (se ainda não existir) e conceda as permissões:

```sql
CREATE USER [sync_login] FOR LOGIN [sync_login];
GRANT SELECT, INSERT, UPDATE ON SCHEMA::itsm TO [sync_login];
GRANT VIEW DEFINITION ON SCHEMA::itsm TO [sync_login];
```

Se uma tabela tiver coluna `IDENTITY`, conceda `ALTER` somente nessa tabela para permitir preservar os valores das chaves. Por exemplo:

```sql
GRANT ALTER ON OBJECT::itsm.analista TO [sync_login];
```

Substitua `sync_login` pelo login configurado nas variáveis `USER`/`PASSWORD` e `TARGET_SQL_USER`/`TARGET_SQL_PASSWORD`. Se o login já tiver usuário no banco, não execute novamente o `CREATE USER`; execute apenas os `GRANT` que faltarem. Para um banco de origem e destino que sejam o mesmo banco, crie o usuário uma vez e conceda o conjunto de permissões necessário para ambos os usos.

### 6. Firewall e conectividade SQL

Se os logs apresentarem erro SQL `40615` ou disserem que o IP do cliente não está autorizado, a conexão está sendo bloqueada pelo firewall do **SQL Server**. No servidor SQL, abra **Rede** e adicione regras para os IPs de saída da Function App, ou configure uma saída de rede estável apropriada para o ambiente. Um IP visto em um único erro pode não ser o único usado pela Function App, especialmente em plano com escala dinâmica. Não habilite acesso amplo sem entender o impacto; a opção que permite acesso de todos os serviços Azure não restringe o acesso à sua Function App.

Erros diferentes indicam etapas diferentes: `40615` é firewall; `18456`/“login failed” indica autenticação ou credencial; erro de tabela, coluna ou chave estrangeira indica estrutura ou permissões do banco.

### 7. Configurações do runtime do Azure Functions

Além das configurações próprias listadas acima, a Function App precisa das configurações de runtime usadas pelo Azure Functions. Confira sem substituir valores gerenciados pelo Portal:

| Configuração | Uso |
| --- | --- |
| `FUNCTIONS_WORKER_RUNTIME` | Deve ser `python`. |
| `FUNCTIONS_EXTENSION_VERSION` | Para Functions v4, normalmente `~4`. |
| `AzureWebJobsStorage` | Armazenamento interno do runtime e do monitoramento de timers. Deve permanecer configurado. Não confundir com `DATALAKE_CONNECTION_STRING`: são recursos/propósitos distintos. |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Telemetria e logs; normalmente criada/integrada pelo Portal. |
| `DEPLOYMENT_STORAGE_CONNECTION_STRING` | Armazenamento de implantação quando usado pelo plano Flex Consumption. Não é a connection string do Data Lake. |

Não apague nem substitua configurações gerenciadas pelo Azure. A configuração do Timer depende do runtime e do armazenamento interno estarem funcionando.

### 8. Fazer a carga inicial e testar manualmente

Primeiro, confirme que a versão atual do código foi **implantada** na Function App e que os snapshots existem no Data Lake. No Portal:

1. Abra a Function App do projeto, acesse **Funções** e selecione `sync_bronze_to_target_db`.
2. Em **Chaves de função**, copie uma function key; trate-a como segredo. Também é possível usar a opção de copiar **Function URL**, que já inclui a chave.
3. Faça uma requisição **POST** para `https://<nome-da-function-app>.azurewebsites.net/api/sync-bronze-to-target-db`. Não precisa de body. Envie a chave no cabeçalho `x-functions-key`.

Exemplo em PowerShell, substituindo os placeholders sem salvar a chave no repositório:

```powershell
$uri = "https://<nome-da-function-app>.azurewebsites.net/api/sync-bronze-to-target-db"
$headers = @{ "x-functions-key" = "<function-key>" }
Invoke-RestMethod -Method Post -Uri $uri -Headers $headers
```

O endpoint executa a mesma carga de todas as entidades que o Timer diário. A resposta de sucesso contém `status: success` e a contagem processada por tabela. Repetir a carga é seguro para duplicações, pois a chave primária direciona a inserção ou atualização.

### 9. Verificar resultado e diagnosticar falhas

No Portal, abra a Function App do projeto, acesse **Funções > sync_bronze_to_target_db > Invocações e muito mais** ou **Monitoramento > Logs**. Confirme a execução e procure mensagens como:

- `Snapshot selecionado para itsm.analista ... (N linhas)`: quantidade carregada do snapshot do Data Lake.
- `Sincronizada itsm.analista: N registros processados`: linhas processadas no destino.
- `Falha ao sincronizar ...` ou `Falha na sincronização sob demanda`: leia a exceção imediatamente anterior no log.

Se o snapshot indicar `0 linhas`, confira a extração de origem `extract_analista` e a tabela `itsm.analista` no banco de origem. Se o log indicar linhas processadas, consulte o banco de destino configurado em `TARGET_SQL_DATABASE`, schema `itsm` e tabela correspondente. O editor SQL do Portal deve estar conectado ao banco de destino correto; atualize os resultados após a execução.

### 10. Carga diária

Após a implantação, `sync_bronze_to_target_db_daily` executa automaticamente todos os dias às 02:00 UTC (23:00 em Brasília). Ela usa os snapshots mais recentes e faz upsert das tabelas. O gatilho HTTP permanece disponível para cargas iniciais e testes manuais. Alterar apenas as variáveis no Portal não implanta código novo; para ativar mudanças no timer, implante a versão atualizada da Function App.
