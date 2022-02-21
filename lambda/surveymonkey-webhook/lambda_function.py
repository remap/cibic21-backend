from common.cibic_common import *

def lambda_handler(event, context):
    try:
        print("surveymonkey-webhook")
        print (event)
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return processedReply()
