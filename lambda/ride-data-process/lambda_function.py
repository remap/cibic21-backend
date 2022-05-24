from common.cibic_common import *

dynamoDbResource = boto3.resource('dynamodb')

# process ride data
# expected payload:
# {
#   'rid': "API-endpoint-request-id",
#   'data': { <ride-data> }
# }
def lambda_handler(event, context):
    try:
        if 'rid' in event and 'data' in event:
            print ('API request {} process ride data {} '.format(event['rid'], str(event['data'])))
            rideDataTable = dynamoDbResource.Table(CibicResources.DynamoDB.RideData)
            rideData = event['data']
            rideDataTable.update_item(
                Key = { 'rideId': rideData['id']},
                UpdateExpression="SET requestId=:rid, userId=:uid, #r=:role1, flow=:flowData, startTime=:start, endTime=:end",
                ExpressionAttributeValues={
                    ':rid': event['rid'],
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
