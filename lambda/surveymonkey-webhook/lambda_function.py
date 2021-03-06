# This Lambda processes the SurveyMonkey webhook for when a survey is completed.
# Get the survey_id and response_id from the event and get the survey from
# SurveyMonkey using the bearer token (which is a Lambda environment variable).
# Also get the userId and role which were in the query parameters of the
# SurveyMonkey web page. Finally, put the result in the DynamoDB table for raw
# survey data.

import boto3
from datetime import datetime, timezone
from common.cibic_common import *

# Python 3.8 lambda environment does not have requests https://stackoverflow.com/questions/58952947/import-requests-on-aws-lambda-for-python-3-8
# for a fix using Lambda Layers, see https://dev.to/razcodes/how-to-create-a-lambda-layer-in-aws-106m
import requests

bearerToken = os.environ['ENV_VAR_SURVEYMONKEY_BEARER_TOKEN']
dynamoDbResource = boto3.resource('dynamodb')

def lambda_handler(event, context):
    surveysTable = dynamoDbResource.Table(CibicResources.DynamoDB.RawSurveyResponses)
    # Make sure it is UTC with the year first so we can sort on it.
    requestTimestamp = datetime.now().astimezone(tz=timezone.utc).isoformat()
    requestId = str(uuid.uuid4()) # generate request uuid
    userId = ''
    role = ''
    surveyId = ''
    requestProcessed = False
    surveyBody = ''
    requestReply = {}
    err = ''

    try:
        print('surveymonkey-webhook event data: ' + str(event))

        if 'event_type' in event and event['event_type'] == 'response_completed':
            surveyId = event['resources']['survey_id']
            response_id = event['object_id']

            print('Fetching surveyId {}, response_id {}'.format(surveyId, response_id))
            response = requests.get(
                'https://api.surveymonkey.net/v3/surveys/' + surveyId +
                '/responses/' + response_id + '/details',
                headers = {'Authorization': 'bearer ' + bearerToken})
            if response.status_code/100 == 2:
                surveyBody = response.json()
                if 'custom_variables' in surveyBody and 'userId' in surveyBody['custom_variables']:
                    userId = surveyBody['custom_variables']['userId']
                if 'custom_variables' in surveyBody and 'role' in surveyBody['custom_variables']:
                    role = surveyBody['custom_variables']['role']

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
    surveysTable.put_item(Item = {
        'timestamp' : requestTimestamp,
        'requestId': requestId,
        'userId': userId,
        'role': role,
        'surveyId': surveyId,
        'body' : json.dumps(surveyBody),
        'processed' : requestProcessed,
        'error' : str(err)
    })

    return requestReply
