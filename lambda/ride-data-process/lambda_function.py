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
                UpdateExpression="SET requestId=:rid, userId=:uid, cibicUser=:cuser, flow=:flowData, startTime=:start, endTime=:end",
                ExpressionAttributeValues={
                    ':rid': event['rid'],
                    ':uid' : rideData['username'] if 'username' in rideData else None,
                    ':cuser': rideData['cibicUser'] if 'cibicUser' in rideData else None,
                    ':flowData': rideData['flow'] if 'flow' in rideData else None,
                    ':start': rideData['startTime'] if 'startTime' in rideData else None,
                    ':end': rideData['endTime'] if 'endTime' in rideData else None
                },
                ReturnValues="UPDATED_NEW"
            )
        else:
            return malformedMessageReply()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return processedReply()
