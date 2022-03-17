from common.cibic_common import *
import os
import psycopg2
from psycopg2 import extras # for fast batch insert, see https://www.psycopg.org/docs/extras.html#fast-exec

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

def lambda_handler(event, context):
    requestReply = {}
    err = ''

    try:
        print('get-user-enrollments event data: ' + str(event))

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
                if not 'id' in enrollment:
                    print('Warning: No user id for enrollment: ' + str(enrollment))
                    continue
                userId = enrollment['id']
                print('Processing enrollment for userId ' + userId)

                role = None
                if 'role' in enrollment:
                    role = enrollment['role']
                homeInfo = getLocationInfo(enrollment, 'homeAddress')
                if homeInfo == None:
                    continue
                workInfo = getLocationInfo(enrollment, 'workAddress')
                if workInfo == None:
                    continue

                insertEnrollment(cur, userId, role, homeInfo, workInfo)

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

def getLocationInfo(enrollment, locationName):
    """
    Return a dict of info for enrollment[locationName] or None if missing fields.
    """
    if not 'homeAddress' in enrollment:
        print('Warning: No ' + locationName + '. Skipping')
        return None

    location = enrollment[locationName]
    if not ('lat' in location and 'long' in location):
        print('Warning: No lat and long. Skipping')
        return None
    coordinate = makeSqlPoint(location['lat'], location['long'])

    # Get optional fields.
    addressText = None
    fullAddress = None
    zipCode = None
    geofenceRadius = None
    if 'text' in location:
        addressText = location['text']
    if 'fullAddress' in location:
        fullAddress = location['fullAddress']
    if 'zipCode' in location:
        zipCode = location['zipCode']
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

def insertEnrollment(cur, userId, role, homeInfo, workInfo):
    """
    Insert the values into the user enrollments table. homeInfo and workInfo are
    from getLocationInfo.
    """
    sql = """
INSERT INTO {} ("userId", "role",
                "homeAddressText", "homeFullAddress", "homeZipCode", "homeCoordinate", "homeGeofenceRadius",
                "workAddressText", "workFullAddress", "workZipCode", "workCoordinate", "workGeofenceRadius")
            VALUES %s
          """.format(CibicResources.Postgres.UserEnrollments)
    values = [(userId, role,
      homeInfo['addressText'], homeInfo['fullAddress'], homeInfo['zipCode'], homeInfo['coordinate'], homeInfo['geofenceRadius'],
      workInfo['addressText'], workInfo['fullAddress'], workInfo['zipCode'], workInfo['coordinate'], workInfo['geofenceRadius'])]
    extras.execute_values(cur, sql, values)
    print('sql query execute result: ' + str(cur.statusmessage))

def makeSqlPoint(lat, lon):
    return str(lon) + ', ' + str(lat)
