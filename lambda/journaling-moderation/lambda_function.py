import base64
import boto3
from boto3.dynamodb.conditions import Key
from common.cibic_common import *

dynamoDbResource = boto3.resource('dynamodb')
rekognition = boto3.client('rekognition')
# Comprehend is not available in us-west-1, so use another region.
comprehend = boto3.client('comprehend', region_name='us-west-2')

snsTopicArn = os.environ['ENV_VAR_SNS_TOPIC_JOURNALING_DATA_READY']

def lambda_handler(event, context):
    unfilteredJournalingTable = dynamoDbResource.Table(
      CibicResources.DynamoDB.UnfilteredJournalingData)
    filteredJournalingTable = dynamoDbResource.Table(
      CibicResources.DynamoDB.FilteredJournalingData)

    try:
        print ('event data ' + str(event))

        if 'Records' in event:
            for rec in event['Records']:
                if 'Sns' in rec and rec['Sns']['TopicArn'] == snsTopicArn:
                    # Get each requestId sent by the processing Lambda.
                    requestIds = json.loads(rec['Sns']['Message'])
                    for requestId in requestIds:
                        dynamodbResponse = unfilteredJournalingTable.query(
                          KeyConditionExpression=Key('requestId').eq(requestId)
                        )
                        # The requestId is supposed to be unique, so assume one item.
                        if (dynamodbResponse['Count'] == 1 and
                            'body' in dynamodbResponse['Items'][0]):
                            body = json.loads(dynamodbResponse['Items'][0]['body'])
                            print('Moderating journaling request {}, body {}'
                              .format(requestId, body))
                            moderateJournalEntry(body)

                            # Store the body of the moderated entry in DynamoDB.
                            filteredJournalingTable.put_item(Item = {
                              'requestId': requestId,
                              'body': json.dumps(body)
                            })
                        else:
                            print("WARNING: No message body in unfilteredJournalingTable, requestId " +
                              requestId)
        else:
            return malformedMessageReply()

        rekognitionResponse = rekognition.detect_moderation_labels(
            Image = { 'Bytes': base64.b64decode(TestImage) }
        )
        print('rekognition response:')
        print(rekognitionResponse)
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return processedReply()

def moderateJournalEntry(body):
    """
    Modify the body of the entry in place by removing moderated content.

    :param body: The journal body which has been converted from JSON into a dict.
    """
    # TODO: What are the important journal entry fields?
    fieldName = 'Bio'
    if fieldName in body:
        text = body[fieldName]

        # Check if the language is English.
        languageCode = ""
        detectLanguageResponse = comprehend.detect_dominant_language(
          Text = text
        )
        if 'Languages' in detectLanguageResponse:
            languageCode = detectLanguageResponse['Languages'][0]['LanguageCode']

        if languageCode == "en":
            # Use Detect PII Entities, which is only available in English.
            comprehendResponse = comprehend.detect_pii_entities(
              LanguageCode = languageCode,
              Text = text
            )
            if 'Entities' in comprehendResponse:
                body[fieldName] = redact(text, comprehendResponse['Entities'])

    return body

def redact(text, entities):
    """
    Return a new string where the substring of each detected entity is replaced
    by a string of stars of equal length.

    :param str text: The text with substrings to redact.
    :param entities: An array of dict with 'BeginOffset' and 'EndOffset' (as
      returned by AWS Comprehend Detect Entities).
    :return: The redacted text.
    :rtype: str
    """
    if len(entities) == 0:
        # Don't need to redact anything.
        return text

    for entity in entities:
        beginOffset = entity['BeginOffset']
        endOffset = entity['EndOffset']
        if endOffset <= beginOffset or beginOffset > len(text) or endOffset > len(text):
            # We don't really expect this.
            continue
        text = text[:beginOffset] + "*" * (endOffset - beginOffset) + text[endOffset:]

    return text
        
TestImage = ("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")
