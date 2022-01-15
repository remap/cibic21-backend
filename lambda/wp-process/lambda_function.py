from common.cibic_common import *

# process waypoints data
# expected payload:
# {
#   'rid': "API-endpoint-request-id",
#   'data': { 'rideId' : "rideId", 'waypoints' : <waypoints-data> }
# }
def lambda_handler(event, context):
    try:
        if 'rid' in event and 'data' in event:
            payload = event['data']
            if 'id' in payload and 'waypoints' in payload:
                rideId = payload['id']
                waypoints = payload['waypoints']
                print ('API request {} process waypoints for ride {} ({} waypoints)'
                    .format(event['rid'], rideId, len(waypoints)))
            else:
                return malformedMessageReply()
        else:
            return malformedMessageReply()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return processedReply()
