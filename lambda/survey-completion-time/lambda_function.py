# This Lambda gets the userId/role from the GET endpoint URL, accesses the DynamoDB
# table for raw survey data, and gets the maximum timestamp for the userId/role
# along with the associated surveyId. It also fetches the outstanding survey CSV
# (or the initial survey CSV if the user has not completed a survey)
# and finds the latest entry where the role matches or is "*".
# Return a JSON dictionary with completionTime, surveyId, availableSurveyId and
# availableSurveyUrl, where each of these is "" if not found.

import boto3
from boto3.dynamodb.conditions import Attr
from common.cibic_common import *

# Python 3.8 lambda environment does not have requests https://stackoverflow.com/questions/58952947/import-requests-on-aws-lambda-for-python-3-8
# for a fix using Lambda Layers, see https://dev.to/razcodes/how-to-create-a-lambda-layer-in-aws-106m
import requests

initialSurveysUrl = os.environ['ENV_VAR_INITIAL_SURVEYS_URL']
outstandingSurveysUrl = os.environ['ENV_VAR_OUTSTANDING_SURVEYS_URL']

dynamoDbResource = boto3.resource('dynamodb')

def lambda_handler(event, context):
    surveysTable = dynamoDbResource.Table(CibicResources.DynamoDB.RawSurveyResponses)

    try:
        print('survey-completion-time event data: ' + str(event))

        stage = event['requestContext']['stage']
        userId = event['pathParameters']['userId']
        role = event['pathParameters']['role']
        print('Getting completion time for: ' + userId + '/' + role)

        response = surveysTable.scan(
          FilterExpression = Attr('userId').eq(userId) &
                             Attr('role').eq(role) &
                             Attr('processed').eq(True),
          # Limit each item to only the timestamp instead of fetching the entire survey.
          # We have to use ExpressionAttributeNames since timestamp is a reserved keyword.
          ProjectionExpression = '#c,surveyId',
          ExpressionAttributeNames = {'#c': 'timestamp'}
        )
        items = response['Items']
        
        reply = {'completionTime': '',
                 'surveyId': '' }
        if len(items) > 0:
            # Get the item with the max timestamp.
            maxItem = None
            for item in items:
                if maxItem == None or item['timestamp'] > maxItem['timestamp']:
                    maxItem = item
            reply['completionTime'] = maxItem['timestamp']
            reply['surveyId'] = maxItem['surveyId']

        if reply['completionTime'] == '':
            # The user has not filled out a survey yet. Get the initial survey.
            surveysUrl = initialSurveysUrl
        else:
            # The user has filled out a survey. Get the outstanding survey.
            surveysUrl = outstandingSurveysUrl
        reply.update(getAvailableSurvey(surveysUrl, role))

        return lambdaReply(200, reply)
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

def getAvailableSurvey(surveysUrl, role):
    """
    Fetch the survey CSV from surveysUrl and find the latest entry where the role
    matches the given role or is "*".
    Return a dictionary where availableSurveyId and availableSurveyUrl are the
    survey ID and URL for the role, or empty strings if not found.
    """
    availableSurveyId = ''
    availableSurveyUrl = ''

    response = requests.get(surveysUrl, stream = True)
    if response.status_code/100 == 2:
        # Get the text and remove CR.
        csv = response.raw.read().decode("utf-8").replace('\r', '')

        for line in csv.split('\n'):
            fields = line.split(',')
            # The fields should be: order,survey id,role,url
            if fields[2] == '*' or fields[2] == role:
                availableSurveyId = fields[1]
                availableSurveyUrl = fields[3]
    else:
        print('Available surveys get failed with code {}'.format(response.status_code))

    return { 'availableSurveyId': availableSurveyId,
             'availableSurveyUrl': availableSurveyUrl }