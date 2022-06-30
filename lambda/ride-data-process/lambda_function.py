from common.cibic_common import *

dynamoDbResource = boto3.resource('dynamodb')

# lambda is triggered by SNS notification
# SNS message expected payload:
# { "id": "<ride-id>", "requestId": "<request-id>", "rideData": {} }
def lambda_handler(event, context):
    try:
      for rec in event['Records']:
        payload = json.loads(rec['Sns']['Message'])
        if 'requestId' in payload and 'rideData' in payload:
            print ('API request {} process ride data {} '.format(payload['requestId'], str(payload['rideData'])))
            rideDataTable = dynamoDbResource.Table(CibicResources.DynamoDB.RideData)
            rideData = payload['rideData']
            rideDataTable.update_item(
                Key = { 'rideId': rideData['id']},
                UpdateExpression="SET requestId=:rid, userId=:uid, #r=:role1, flow=:flowData, startTime=:start, endTime=:end",
                ExpressionAttributeValues={
                    ':rid': payload['requestId'],
                    ':uid' : rideData.get('userId'),
                    ':role1': rideData.get('role'),
                    ':flowData': rideData.get('flow'),
                    ':start': rideData.get('startTime'),
                    ':end': rideData.get('endTime')
                },
                # We have to use ExpressionAttributeNames since role is a reserved keyword.
                ExpressionAttributeNames = {'#r': 'role'},
                ReturnValues="UPDATED_NEW"
            )
        else:
            return malformedMessageReply()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return processedReply()
