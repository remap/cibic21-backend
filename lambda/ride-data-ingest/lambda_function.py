import boto3
import os
import uuid
import gzip
import base64
from common.cibic_common import *
from datetime import datetime

dynamoDbResource = boto3.resource('dynamodb')
lambdaClient = boto3.client('lambda')

# resource ARNs must be defined as lambda environment variables
# see https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html#configuration-envvars-config
# requestTableArn = os.environ['ENV_DYNAMODB_ENDPOINT_REQUESTS_TABLE_NAME']
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
            waypointsData = requestBody['trajectoryData']['waypoints']

            remapRideData = makeRideData(requestBody)

            # To send the waypoints, we gzip and base64.
            waypoints_gz = gzip.compress(str.encode(json.dumps(waypointsData)))
            # async-invoke waypoints processing lambda
            res = lambdaClient.invoke(FunctionName = waypointsProcArn,
                                InvocationType = 'Event',
                                Payload = json.dumps({
                                                        'rid': requestId,
                                                        'data':
                                                        {
                                                            'rideData' : remapRideData,
                                                            'flowData' : requestBody.get('flow'),
                                                            'waypoints_gz_b64' : base64.b64encode(waypoints_gz).decode()
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
    return 'id' in body and 'trajectoryData' in body

def makeRideData(body):
    # for example, throw out data that we don't need
    flowId = None
    if body.get('flow') != None:
        flowId = body['flow'].get('_id') # TODO: Should this be 'id'?
    rideData = {
        'id' : body['id'],
        'commute' : body.get('commute'),
        'flow': flowId
        }

    if 'cibicUser' in body:
        cibicUser = body['cibicUser']
        if 'username' in cibicUser:
           rideData['userId'] = cibicUser['username']
        if 'role' in cibicUser:
           rideData['role'] = cibicUser['role']

    return rideData
