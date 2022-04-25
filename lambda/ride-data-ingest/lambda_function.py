import boto3
import os
import uuid
from common.cibic_common import *
from datetime import datetime

dynamoDbResource = boto3.resource('dynamodb')
lambdaClient = boto3.client('lambda')

# resource ARNs must be defined as lambda environment variables
# see https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html#configuration-envvars-config
# requestTableArn = os.environ['ENV_DYNAMODB_ENDPOINT_REQUESTS_TABLE_NAME']
rideDataProcArn = os.environ['ENV_LAMBDA_ARN_RIDE_DATA_PROC']
waypointsProcArn = os.environ['ENV_LAMBDA_ARN_WP_PROC']

def lambda_handler(event, context):
    requestsTable = dynamoDbResource.Table(CibicResources.DynamoDB.EndpointRequests)
    requestTimestamp = datetime.now().astimezone().isoformat()
    requestId = str(uuid.uuid4()) # generate request uuid
    requestProcessed = False
    requestBody = ''
    requestReply = {}
    err = ''

    try:
        print ('event data ' + str(event))
        stage = event['requestContext']['stage']
        requestBody = json.loads(event['body'])
        print('body data ' + str(requestBody))
        print('requestId ' + requestId)

        # here's what we need to do with incoming data:
        # - make sure it's valid, i.e. has required fields (TODO: this should be probably done at the API endpoint using data models)
        # - extract data that we need for storing and anonymize it here (remove user ids? names? other?...)
        # - extract waypoints array, with it:
        #       - obfuscate home/work: using a radius parameter remove waypoints on both ends of the route
        #       - generate circle geometry (i.e. center + radius in meters) for home/end (circle centers MUST NO be at the start/end waypoint)
        # - remaining waypoints process through snapping algorithm
        # - store data:
        #       - DynamoDB:
        #           - anonymized ride data
        #       - Postgres:
        #           - raw waypoints after removed home/work areas
        #           - snapped waypoints after removed home/work areas
        #           - route path (snapped, with home/work circles), retrievable as GeoJSON
        #

        # validate
        if not isRideDataValid(requestBody):
            requestReply = malformedMessageReply();
        else:
            rideId = requestBody['_id']
            waypointsData = requestBody['trajectoryData']['waypoints']

            remapRideData = makeRideData(requestBody)
            # async-invoke ride data processing lambda
            res = lambdaClient.invoke(FunctionName = rideDataProcArn,
                                InvocationType = 'Event',
                                Payload = json.dumps({
                                                        'rid': requestId,
                                                        'data': remapRideData
                                                    })
                                )
            print('ride-proc async-invoke reply status code '+str(res['StatusCode']))

            # async-invoke waypoints processing lambda
            res = lambdaClient.invoke(FunctionName = waypointsProcArn,
                                InvocationType = 'Event',
                                Payload = json.dumps({
                                                        'rid': requestId,
                                                        'data':
                                                        {
                                                            'id' : rideId,
                                                            'waypoints': waypointsData
                                                        }
                                                    })
                                )
            print('wp-proc async-invoke reply status code '+str(res['StatusCode']))

            requestProcessed = True
            requestReply = lambdaReply(200, {
              'reply': 'Message processed',
              'requestId': requestId })
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        requestReply = lambdaReply(420, str(err))

    # store request data in DynamoDB table
    requestsTable.put_item(Item = {
        'timestamp' : requestTimestamp,
        'requestId': requestId,
        'body' : json.dumps(requestBody),
        'processed' : requestProcessed,
        'error' : str(err)
    })

    return requestReply

def isRideDataValid(body):
    # TODO: add proper JSON validation by data model
    return '_id' in body and 'trajectoryData' in body

def makeRideData(body):
    # for example, throw out data that we don't need
    rideData = {
        'id' : body['_id'],
        'flow': body['flow'],
        'startTime': body['startTime'],
        'endTime': body['endTime']
        }
    return rideData
