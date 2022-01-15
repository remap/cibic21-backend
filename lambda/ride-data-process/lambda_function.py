from common.cibic_common import *

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

        else:
            return malformedMessageReply()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return processedReply()
