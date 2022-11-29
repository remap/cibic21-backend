# This Lambda is for the user ride statistics API. The optional query parameters
# are 'startTime', 'endTime', 'region' and 'organization'. Get all active users
# plus the number of rides matching the query parameters. Return JSON with
# userId, name, email, outward and inward flow names and total rides.

from common.cibic_common import *
import os
import psycopg2
from datetime import datetime
import urllib

pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']
pgServer = os.environ['ENV_VAR_POSTGRES_SERVER']

def lambda_handler(event, context):
    try:
        print (event)
        if event['requestContext']['resourcePath'] == '/get':
            region = event['queryStringParameters'].get('region')
            organization = event['queryStringParameters'].get('organization')
            startTime = parseDatetime(event['queryStringParameters'].get('startTime'))
            endTime = parseDatetime(event['queryStringParameters'].get('endTime'))

            userData = fetchUserRideStatistics(region, organization, startTime, endTime)
            if userData:
                return lambdaReply(200, userData)
            else:
                print('no users matching query parameters found')
                return lambdaReply(404, 'not found')
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return processedReply()

def fetchUserRideStatistics(region, organization, startTime, endTime):
    """
    Get active, non-deleted user enrollments and add the count of matching rides
    where the flow is not NULL and between startTime and endTime (if not None).
    If region is not None, restrict to the region.
    If organization is not None, restrict to the organization.
    """
    extraUsersWhere = ''
    if region != None:
        extraUsersWhere += " AND region = '{}'".format(region)
    if organization != None:
        extraUsersWhere += " AND organization = '{}'".format(organization)

    extraRidesWhere = ''
    if startTime != None:
        extraRidesWhere += " AND rides.\"startTime\" >= '{}'".format(
          startTime.astimezone().strftime("%Y-%m-%d %H:%M:%S%z"))
    if endTime != None:
        extraRidesWhere += " AND rides.\"startTime\" < '{}'".format(
          endTime.astimezone().strftime("%Y-%m-%d %H:%M:%S%z"))

    sql = """
SELECT json_build_object(
         'userId', "userId",
         'role', role,
         'displayName', "displayName",
         'email', email,
         'outwardFlowId', "outwardFlowId",
         'outwardFlowName', "outwardFlowName",
         'returnFlowId', "returnFlowId",
         'returnFlowName', "returnFlowName",
         'totalRides', (SELECT COUNT(*) FROM {1} AS rides
                        WHERE rides."userId" = users."userId" AND
                        rides.flow IS NOT NULL {3}),
         'lastFlowId', last_flow_info[1],
         'lastFlowName', last_flow_info[2]
       )
FROM (SELECT "userId", role, "displayName", email,
      "outwardFlowId", "outwardFlowName", "returnFlowId", "returnFlowName",
      (SELECT array[flow, "flowName"]
	     FROM {1} AS rides
	     WHERE rides."userId" = u."userId" AND rides.flow IS NOT NULL {3}
	     ORDER BY rides."startTime" DESC
	     LIMIT 1) AS last_flow_info
      FROM {0} AS u
      WHERE active = True AND deleted = False {2}
      ORDER BY "userId") AS users;
          """.format(CibicResources.Postgres.UserEnrollments,
                     CibicResources.Postgres.Rides, extraUsersWhere, extraRidesWhere)
    conn = psycopg2.connect(host=pgServer, database=pgDbName,
                            user=pgUsername, password=pgPassword)
    cur = conn.cursor()
    cur.execute(sql)

    userData = []
    for r in cur.fetchall():
        userData.append(r[0])
    conn.commit()
    cur.close()

    return userData

def parseDatetime(ss):
    try:
        return datetime.fromisoformat(urllib.parse.unquote(ss))
    except:
        return None
