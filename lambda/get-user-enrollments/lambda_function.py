# This Lambda queries SurveyMonkey for consent surveys and gets the user name,
# email and phone, as well as the latest completion time for the name.
# This also queries the upstream endpoint to get the user enrollments, and to
# save a processed version in a Postgres table. (The Lambda for the API to query
# the Posgres table and return the user enrollments is query-user-enrollments.)
# This Lmabda has a trigger to run periodically (i.e. each hour).

from common.cibic_common import *
import os
import psycopg2
import unidecode
from psycopg2 import extras # for fast batch insert, see https://www.psycopg.org/docs/extras.html#fast-exec
from datetime import datetime

# Python 3.8 lambda environment does not have requests https://stackoverflow.com/questions/58952947/import-requests-on-aws-lambda-for-python-3-8
# for a fix using Lambda Layers, see https://dev.to/razcodes/how-to-create-a-lambda-layer-in-aws-106m
import requests
from requests.auth import HTTPBasicAuth

enrollmentsEndpointUrl = os.environ['ENV_VAR_ENROLLMENTS_EP_URL']
enrollmentsEndpointUsername = os.environ['ENV_VAR_ENROLLMENTS_EP_USERNAME']
enrollmentsEndpointPassword = os.environ['ENV_VAR_ENROLLMENTS_EP_PASSWORD']
pgServer = os.environ['ENV_VAR_POSTGRES_SERVER']
pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']
bearerToken = os.environ['ENV_VAR_SURVEYMONKEY_BEARER_TOKEN']
consentSurveyId = os.environ['ENV_VAR_CONSENT_SURVEY_ID']
consentSurveyNameRowId = os.environ['ENV_VAR_CONSENT_SURVEY_NAME_ROW_ID']
consentSurveyEmailRowId = os.environ['ENV_VAR_CONSENT_SURVEY_EMAIL_ROW_ID']
consentSurveyPhoneRowId = os.environ['ENV_VAR_CONSENT_SURVEY_PHONE_ROW_ID']

def lambda_handler(event, context):
    requestReply = {}
    err = ''

    try:
        print('get-user-enrollments event data: ' + str(event))

        consentedUsersByEmail = {}
        consentedUsersByName = getConsentedUsers()
        if consentedUsersByName != None:
            # Fill consentedUsersByEmail where the key is the lower-case email.
            for _, consentedUser in consentedUsersByName.items():
                consentedEmail = consentedUser.get('email')
                if consentedEmail != None:
                    consentedUsersByEmail[consentedEmail.lower()] = consentedUser
              
        # Fetch from the enrollments endpoint.
        response = requests.request("GET", enrollmentsEndpointUrl,
          auth=HTTPBasicAuth(enrollmentsEndpointUsername, enrollmentsEndpointPassword))
        if response.status_code/100 == 2:
            enrollments = response.json()
            print('Processing ' + str(len(enrollments)) + ' user enrollments')

            conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                    user=pgUsername, password=pgPassword)
            cur = conn.cursor()

            # This has all current enrollments, and maybe some were removed, so
            # first delete all records.
            cur.execute("DELETE FROM {}".format(CibicResources.Postgres.UserEnrollments))

            for enrollment in enrollments:
                # Get required fields.
                if not 'username' in enrollment:
                    print('Warning: No username for enrollment: ' + str(enrollment))
                    continue
                userId = enrollment['username']
                print('Processing enrollment for userId ' + userId)

                role = enrollment.get('role')
                active = enrollment.get('active')
                displayName = enrollment.get('displayName')
                if displayName != None:
                    displayName = displayName.strip()
                email = enrollment.get('email')
                if email != None:
                    email = email.strip()

                # Get flow IDs and names.
                outwardFlowId = enrollment.get('outwardTripFlow', {}).get('id')
                if outwardFlowId == None:
                    # Still using the old key.
                    outwardFlowId = enrollment.get('outwardTripFlow', {}).get('_id')
                outwardFlowName = enrollment.get('outwardTripFlow', {}).get('name')
                returnFlowId = enrollment.get('returnTripFlow', {}).get('id')
                if returnFlowId == None:
                    # Still using the old key.
                    returnFlowId = enrollment.get('returnTripFlow', {}).get('_id')
                returnFlowName = enrollment.get('returnTripFlow', {}).get('name')

                # Get related pod IDs and names.
                outwardPodId = None
                outwardPodName = None
                returnPodId = None
                returnPodName = None
                if outwardFlowId != None:
                    (outwardPodId, outwardPodName) = getPodForUser(enrollment['outwardTripFlow'], userId)
                if returnFlowId != None:
                    (returnPodId, returnPodName) = getPodForUser(enrollment['returnTripFlow'], userId)

                homeInfo = getLocationInfo(enrollment, 'homeAddress')
                if homeInfo == None:
                    continue
                workInfo = getLocationInfo(enrollment, 'workAddress')
                if workInfo == None:
                    continue

                consentedUser = None
                # First try to match by email.
                if email != None:
                    consentedUser = consentedUsersByEmail.get(email.lower())
                    if consentedUser != None:
                        # Save for checking later.
                        consentedUser['inserted'] = True
                if consentedUser == None:
                    # Now try to match by canonical name.
                    if consentedUsersByName != None and displayName != None:
                        consentedUser = consentedUsersByName.get(getCanonicalUserName(displayName))
                        if consentedUser != None:
                            # Save for checking later.
                            consentedUser['inserted'] = True

                insertEnrollment(cur, userId, role, active, displayName, email, outwardFlowId, outwardFlowName,
                  returnFlowId, returnFlowName, outwardPodId, outwardPodName,
                  returnPodId, returnPodName, homeInfo, workInfo, consentedUser)

            # Check for consented users which didn't match an enrollment.
            noEnrollmentCount = 0
            if consentedUsersByName != None:
                for _, consentedUser in consentedUsersByName.items():
                    if consentedUser.get('inserted') == True:
                        continue

                    # Make a phantom userId and insert a null enrollment with the consent info.
                    noEnrollmentCount += 1
                    insertEnrollment(cur, '(no-enrollment-{:03})'.format(noEnrollmentCount),
                      None, False, None, None, None, None, None, None, None, None, None, None,
                      { 'coordinate': '0,0', 'addressText': None, 'fullAddress': None, 'zipCode': None, 'geofenceRadius': None },
                      { 'coordinate': '0,0', 'addressText': None, 'fullAddress': None, 'zipCode': None, 'geofenceRadius': None },
                      consentedUser)

            conn.commit()
            cur.close()

            requestReply = processedReply()
        else:
            err = 'Enrollments endpoint request failed with code {}'.format(response.status_code)
            print(err)
            requestReply = lambdaReply(420, str(err))
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return requestReply

def getPodForUser(flow, userId):
    """
    Search the flow for the first pod which mentions the userId and return
    (podId, podName). If not found, return (None, None)
    """
    if 'pods' in flow:
        for pod in flow['pods']:
            if 'members' in pod:
                for member in pod['members']:
                    if member.get('username') == userId:
                        return (pod.get('id'), pod.get('name'))

    # Not found
    return (None, None)

def getLocationInfo(enrollment, locationName):
    """
    Return a dict of info for enrollment[locationName] or None if missing fields.
    """
    if not locationName in enrollment:
        print('Warning: No ' + locationName + '. Skipping')
        return None

    location = enrollment[locationName]
    if not ('lat' in location and 'long' in location):
        print('Warning: No lat and long. Skipping')
        return None
    coordinate = makeSqlPoint(location['lat'], location['long'])

    # Get optional fields.
    addressText = location.get('text')
    fullAddress = location.get('fullAddress')
    zipCode = location.get('zipCode')
    geofenceRadius = None
    if 'text' in location and (type(location['geofenceRadius']) == int or
                               type(location['geofenceRadius']) == float):
        geofenceRadius = float(location['geofenceRadius'])

    return {
      'coordinate': coordinate,
      'addressText': addressText,
      'fullAddress': fullAddress,
      'zipCode': zipCode,
      'geofenceRadius': geofenceRadius
    }

def getConsentedUsers():
    """
    Fetch completed consent surveys from SurveyMonkey and process the 'completed' surveys.
    (Assume that a 'completed' survey gives consent.)
    Return a dict where the key is the canonical name (lower case, not accents),
    and the values is a dict of 'time' (as datetime), 'name', 'email', 'phone'.
    Only return the latest entry for the canonical name.
    If problem, print an error and return None.
    """
    try:
        # TODO: Check 'total' and fetch multiple pages.
        # TODO: Don't use /bulk for the initial fetch.
        response = requests.get(
            'https://api.surveymonkey.net/v3/surveys/' + consentSurveyId +
            '/responses/bulk?per_page=100',
            headers = {'Authorization': 'bearer ' + bearerToken})
        if response.status_code/100 != 2:
            raise ValueError('SurveyMonkey API request failed with code {}'.format(response.status_code))

        surveyBody = response.json()
        result = {}
        gotConsentSurveyNameRowId = False
        gotConsentSurveyEmailRowId = False
        gotConsentSurveyPhoneRowId = False

        for response in surveyBody['data']:
            if not response.get('response_status') == 'completed':
                continue
            time = datetime.fromisoformat(response['date_modified'])

            name = None
            email = None
            phone = None
            # Find the rows with the name, email and phone.
            for page in response['pages']:
                if not 'questions' in page:
                    continue
                for question in page['questions']:
                    for answer in question['answers']:
                        if answer.get('row_id') == consentSurveyNameRowId:
                            gotConsentSurveyNameRowId = True
                            name = answer.get('text')
                        elif answer.get('row_id') == consentSurveyEmailRowId:
                            gotConsentSurveyEmailRowId = True
                            email = answer.get('text')
                        elif answer.get('row_id') == consentSurveyPhoneRowId:
                            gotConsentSurveyPhoneRowId = True
                            phone = answer.get('text')

            if name != None:
                canonicalName = getCanonicalUserName(name)
                # Replace an earlier entry for the same canonicalName.
                if not canonicalName in result or time > result[canonicalName]['time']:
                    result[canonicalName] = {
                        'time': time,
                        'name': name.strip(),
                        'email': None if email == None else email.strip(),
                        'phone': None if phone == None else phone.strip()
                    }

        if not gotConsentSurveyNameRowId:
            raise ValueError("No survey has a name row id " + str(consentSurveyNameRowId))
        if not gotConsentSurveyEmailRowId:
            raise ValueError("No survey has an email row id " + str(consentSurveyEmailRowId))
        if not gotConsentSurveyPhoneRowId:
            raise ValueError("No survey has a phone row id " + str(consentSurveyPhoneRowId))

        return result
    except:
        reportError()
        return None

def getCanonicalUserName(name):
    """
    Get the canonical name by removing accents, leading/trailing whitespace and making lower case.
    """
    return unidecode.unidecode(name).lower().strip()

def insertEnrollment(cur, userId, role, active, displayName, email, outwardFlowId, outwardFlowName,
      returnFlowId, returnFlowName, outwardPodId, outwardPodName,
      returnPodId, returnPodName, homeInfo, workInfo, consentedUser):
    """
    Insert the values into the user enrollments table. homeInfo and workInfo are
    from getLocationInfo(). If not None, consentedUser is an item returned by
    getConsentedUsers().
    """
    consentedName = None
    consentedEmail = None
    consentedPhone = None
    consentedTime = None
    if consentedUser != None:
        consentedName = consentedUser['name']
        consentedEmail = consentedUser['email']
        consentedPhone = consentedUser['phone']
        consentedTime = consentedUser['time']

    sql = """
INSERT INTO {} ("userId", "role", "active", "displayName", "email",
                "consentedName", "consentedEmail", "consentedPhone", "consentedTime",
                "outwardFlowId", "outwardFlowName", "returnFlowId", "returnFlowName",
                "outwardPodId", "outwardPodName", "returnPodId", "returnPodName",
                "homeAddressText", "homeFullAddress", "homeZipCode", "homeCoordinate", "homeGeofenceRadius",
                "workAddressText", "workFullAddress", "workZipCode", "workCoordinate", "workGeofenceRadius")
            VALUES %s
          """.format(CibicResources.Postgres.UserEnrollments)
    values = [(userId, role, active, displayName, email,
               consentedName, consentedEmail, consentedPhone, consentedTime,
               outwardFlowId, outwardFlowName, returnFlowId, returnFlowName,
               outwardPodId, outwardPodName, returnPodId, returnPodName,
      homeInfo['addressText'], homeInfo['fullAddress'], homeInfo['zipCode'], homeInfo['coordinate'], homeInfo['geofenceRadius'],
      workInfo['addressText'], workInfo['fullAddress'], workInfo['zipCode'], workInfo['coordinate'], workInfo['geofenceRadius'])]
    extras.execute_values(cur, sql, values)
    print('sql query execute result: ' + str(cur.statusmessage))

def makeSqlPoint(lat, lon):
    return str(lon) + ', ' + str(lat)

