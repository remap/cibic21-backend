from common.cibic_common import *
import json

dynamoDbResource = boto3.resource('dynamodb')

# process derived data, triggered by SNS
# expected payload (SNS['Message']):
# {
#   "id" : "<ride-id>",
#   "derivedData": [ {<derived-data-dict1>}, {<derived-data-dict2>}, ...]
# }
# lambda can be invoked multiple times whenever derived data ready notification
# is sent. derived data array will be appended with new items
def lambda_handler(event, context):
    try:
        for rec in event['Records']:
            payload = json.loads(rec['Sns']['Message'])
            if 'id' in payload and 'derivedData' in payload:
                print ('adding derived data for ride id {}'.format(payload['id']))
                print(payload)

                rideDataTable = dynamoDbResource.Table(CibicResources.DynamoDB.RideData)
                # AWS DynamoDB update_item with SET list_append does not take float
                # values, so we have to round floats to decimals
                derivedData = [roundToDecimal(x) for x in payload['derivedData']]
                rideDataTable.update_item(
                    Key = { 'rideId': payload['id']},
                    UpdateExpression="SET derivedData=list_append(if_not_exists(derivedData, :emptyList), :val)",
                    ExpressionAttributeValues={
                        ':val': payload['derivedData'],
                        ':emptyList' : []
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

def roundToDecimal(stat):
    for k,v in stat.items():
        if type(v) == dict:
            roundToDecimal(v)
        elif type(v) == float:
            stat[k] = round(v)
