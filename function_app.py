import logging
import azure.functions as func
import requests
import os

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
        try:
            req_body = req.get_json()
        except ValueError:
            pass
        else:
            name = req_body.get('name', 'desconhecido')

    if name:
        return func.HttpResponse(f"Hello, {name}. This HTTP triggered function executed successfully.")
    else:
        return func.HttpResponse(
             "This HTTP triggered function executed successfully. Pass a name in the query string or in the request body for a personalized response.",
             status_code=200
        )

@app.timer_trigger(schedule="0 * * * * *", arg_name="myTimer", run_on_startup=False,
              use_monitor=False) 
def timer_trigger_http(myTimer: func.TimerRequest) -> None:
    
    logging.info('Iniciando a time trigger http')

    host = os.environ.get("WEBSITE_HOSTNAME")
    url =f"https://{host}/api/http_trigger"

    payload = {'name': 'vitor'}
    headers= {"Content-Type": "application/json"}

    try:
        response = requests.post(url, json=payload, headers=headers )

        logging.info(f'response {str(response)}')
    except Exception as e:
        logging.error(f"Falha ao tentar se comunicar com a função interna: {str(e)}")

    logging.info('Python timer trigger function executed.')