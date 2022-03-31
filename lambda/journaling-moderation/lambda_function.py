import base64
import boto3
from boto3.dynamodb.conditions import Key
from common.cibic_common import *

dynamoDbResource = boto3.resource('dynamodb')
rekognition = boto3.client('rekognition')
# Comprehend is not available in us-west-1, so use another region.
comprehend = boto3.client('comprehend', region_name='us-west-2')

def lambda_handler(event, context):
    moderatedRequestsTable = dynamoDbResource.Table(CibicResources.DynamoDB.ModeratedJournalingRequests)
    timestamp = ''
    requestId = ''
    userId = ''
    role = ''
    body = ''
    processed = False
    requestReply = {}
    err = ''

    try:
        print ('event data ' + str(event))
        stage = event['stage']

        if 'timestamp' in event and 'requestId' in event and 'body' in event:
            timestamp = event['timestamp']
            requestId = event['requestId']
            body = event['body']
            if 'userId' in body:
                userId = body['userId']
            if 'role' in body:
                role = body['role']

            print('Moderating journal body for requestId {}, userId {}, role {}, body {}'
              .format(requestId, userId, role, body))
            moderateJournalEntry(body)

            processed = True
            requestReply = processedReply()
        else:
            requestReply = malformedMessageReply()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        requestReply = lambdaReply(420, str(err))

    if timestamp != '':
        # Store request data in moderated DynamoDB table.
        moderatedRequestsTable.put_item(Item = {
            'timestamp' : timestamp,
            'requestId': requestId,
            'userId': userId,
            'role': role,
            'body' : json.dumps(body),
            'processed' : processed,
            'error' : str(err)
        })

    return requestReply

def moderateJournalEntry(body):
    """
    Modify the body of the entry in place by redacting moderated text and
    removing moderated images.

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

    fieldName = 'image'
    imageModerationLabels = None
    if fieldName in body and body[fieldName] != None and body[fieldName] != "":
        imagePath = body[fieldName]

        # Check the image directly in S3.
        response = rekognition.detect_moderation_labels(
            Image = { 'S3Object': {
              'Bucket': CibicResources.S3Bucket.JournalingImages,
              'Name': imagePath
            }}
        )
        if 'ModerationLabels' in response and response['ModerationLabels'] != []:
            imageModerationLabels = response['ModerationLabels']
            print('Image "{}". ModerationLabels: {}'.format(imagePath, imageModerationLabels))
    body['imageModerationLabels'] = imageModerationLabels

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
