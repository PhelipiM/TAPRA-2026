import logging
import os
import azure.functions as func
import requests

import pyodbc

app = func.FunctionApp()

@app.timer_trigger(schedule="0 */3 * * * *", arg_name="myTimer", run_on_startup=False,
              use_monitor=False) 
def timer_trigger_taprafunc1(myTimer: func.TimerRequest) -> None:
    if myTimer.past_due:
        logging.info('Eita, demorou demais!')

    logging.info('Aqui é o timer trigger, rodando a cada 3 minutos!')

@app.route(route="http_trigger", auth_level=func.AuthLevel.ANONYMOUS)
def http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    name = req.params.get('name')
    if not name:
        return func.HttpResponse(
            "Informe o parametro name na URL.",
            status_code=400
        )

    logging.info(f"Parametro recebido: {name}")

    return func.HttpResponse(
        f"Informacao recebida: {name}. Esta mensagem foi retornada pela HTTP Function."
    )


@app.timer_trigger(schedule="0 */5 * * * *", arg_name="myTimer", run_on_startup=False,
              use_monitor=False)
def timer_trigger_http(myTimer: func.TimerRequest) -> None:

    logging.info('Iniciando a time trigger http')

    host = os.environ.get("WEBSITE_HOSTNAME")
    url = f"https://{host}/api/http_trigger"

    payload = {'name': 'nome exemplo'}

    try:
        response = requests.get(url, params=payload, timeout=10)
        response.raise_for_status()

        logging.info(f'Timer trigger chamou a HTTP function. Status: {response.status_code} | Retorno: {response.text}')
    except Exception as e:
        logging.error(f"Falha ao tentar se comunicar com a função interna: {str(e)}")

    logging.info('Finalizando a time trigger http')


@app.timer_trigger(schedule="0 * * * * *", arg_name="myTimer", run_on_startup=False,
              use_monitor=False) 
def extract_chamado(myTimer: func.TimerRequest) -> None:

    driver = "{ODBC Driver 18 for SQL Server}"
    host_sql = os.getenv("HOST")
    database_sql = os.getenv("DATABASE")
    user_sql = os.getenv("USER")
    pass_sql = os.getenv("PASSWORD")

    #string de conexao
    connection_string = (
        f"Driver={driver};"
        f"Server=tcp:{host_sql},1433;"
        f"Database={database_sql};"
        f"Uid={user_sql};"
        f"Pwd={pass_sql};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )

    #tentativa de conexao
    try:
        conexao = pyodbc.connect(connection_string)
        cursor = conexao.cursor()

        logging.info("conectado com sucesso negão")
        
        query = "SELECT * FROM itsm.chamado"

        cursor.execute(query)

        retorno = cursor.fetchall()

        logging.info(retorno)
        
        cursor.close()
        conexao.close()
        logging.info("conexao fechada")
    except Exception as e:
        print(f"Erro ao conectar: {e}")