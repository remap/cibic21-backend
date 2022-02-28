import boto3
from common.cibic_common import *

# Python 3.8 lambda environment does not have requests https://stackoverflow.com/questions/58952947/import-requests-on-aws-lambda-for-python-3-8
# for a fix using Lambda Layers, see https://dev.to/razcodes/how-to-create-a-lambda-layer-in-aws-106m
import requests

bearer_token = os.environ['ENV_VAR_SURVEYMONKEY_BEARER_TOKEN']
dynamoDbResource = boto3.resource('dynamodb')

def lambda_handler(event, context):
    requestsTable = dynamoDbResource.Table(CibicResources.DynamoDB.RawSurveyResponses)
    requestTimestamp = datetime.now().astimezone().strftime("%m/%d/%Y %H:%M:%S.%f UTC%z")
    requestId = str(uuid.uuid4()) # generate request uuid
    requestProcessed = False
    surveyBody = ''
    requestReply = {}
    err = ''

    try:
        print('surveymonkey-webhook event data: ' + str(event))

        if 'event_type' in event and event['event_type'] == 'response_completed':
            survey_id = event['resources']['survey_id']
            response_id = event['object_id']

            print('Fetching survey_id {}, response_id {}'.format(survey_id, response_id))
            response = requests.get(
                'https://api.surveymonkey.net/v3/surveys/' + survey_id +
                '/responses/' + response_id + '/details',
                headers = {'Authorization': 'bearer ' + bearer_token})
            if response.status_code/100 == 2:
                surveyBody = response.json()

                requestProcessed = True
                requestReply = processedReply()
            else:
                err = 'SurveyMonkey API request failed with code {}'.format(response.status_code)
                print(err)
                requestReply = lambdaReply(420, str(err))
        else:
            err = 'SurveyMonkey API webhook message event_type is not response_completed'
            print(err)
            requestReply = malformedMessageReply()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        requestReply = lambdaReply(420, str(err))

    # Store survey data in DynamoDB table.
    requestsTable.put_item(Item = {
        'timestamp' : requestTimestamp,
        'requestId': requestId,
        'body' : json.dumps(surveyBody),
        'processed' : requestProcessed,
        'error' : str(err)
    })

    return requestReply
