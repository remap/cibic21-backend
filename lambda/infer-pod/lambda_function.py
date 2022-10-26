# Infer the pod for a ride.

from common.cibic_common import *
import os
import psycopg2

pgDbName = os.environ['ENV_VAR_POSTGRES_DB']
pgUsername = os.environ['ENV_VAR_POSTGRES_USER']
pgPassword = os.environ['ENV_VAR_POSTGRES_PASSWORD']
pgServer = os.environ['ENV_VAR_POSTGRES_SERVER']

def lambda_handler(event, context):
    print("event: " + str(event))

    # TODO: Run this on a timer. Keep trying to infer the pod for null inferredPod up to a day after the rides' endTime. If after a day, set to 'unknown'.
    try:
        if not 'rideIds' in event:
            return malformedMessageReply()

        conn = psycopg2.connect(host=pgServer, database=pgDbName,
                                user=pgUsername, password=pgPassword)
        cur = conn.cursor()

        for rideId in event['rideIds']:
            print('Inferring pod for rideId ' + rideId)

            # Get the ride.
            sql = """
SELECT "startTime", "endTime", flow, role, region, organization
  FROM {0}
  WHERE "rideId" = '{1}';
            """.format(CibicResources.Postgres.Rides, rideId)
            cur.execute(sql)
            ride = cur.fetchone()
            if ride == None:
                print('caught exception: Cannot get rideId ' + rideId)
                continue

            startTime = ride[0]
            endTime = ride[1]
            flow = ride[2]
            role = ride[3]
            region = ride[4]
            organization = ride[5]

            if role == 'steward':
                # TODO: If not already, set inferredPod to pod.
                print('The user in rideId ' + rideId + ' is already a steward')
                continue

            # Get all steward rides for the same flow, region and organization where times overlap.
            sql = """
SELECT pod, "podName", "flowJoinPointsJson"
  FROM {0}
  WHERE role = 'steward' AND flow = '{1}' AND region = '{2}' AND organization = '{3}' AND
        "endTime" > '{4}' AND "startTime" < '{5}';
            """.format(CibicResources.Postgres.Rides, flow, region, organization,
                       startTime, endTime)
            cur.execute(sql)
            stewardRides = cur.fetchall()
            if len(stewardRides) == 0:
                print('There are no matching steward rides for rideId ' + rideId)
                # TODO: Set inferredPod to 'unknown'
                continue

            # Check if all steward rides have the same pod.
            inferredPod = stewardRides[0][0]
            inferredPodName = stewardRides[0][1]
            for i in range(1, len(stewardRides)):
                joinPoints = stewardRides[i][2]
                if stewardRides[i][0] != inferredPod and joinPoints != None and len(joinPoints) > 0:
                    # Found a steward ride with a different pod, which has join points to examine.
                    inferredPod = None
                    inferredPodName = None
                    break

            # TODO: For Buenos Aires, is the pod name just the steward userId? 
            inferredPod = None # For debugging, force choosing a pod.
            if inferredPod == None:
                # There are steward rides with different pods. Must choose.
                for stewardRide in stewardRides:
                    joinPoints = stewardRide[2]
                    if joinPoints == None or len(joinPoints) == 0:
                        continue

                    # TODO: May need to sort join points by distance from first flow waypoint.
                    finalJoinPoint = joinPoints[-1]
                    finalJoinPointLeaveTime = getPointLeaveTime(
                      cur, rideId, centralJoinPoint['lat'], centralJoinPoint['long'])

                    # TODO: Get the rider's waypoint at finalJoinPointLeaveTime.
                    # TODO: Compute rider's distance to finalJoinPoint. Get the closes for all steward rides. It's pod is the inferredPod.

            print("Debug inferredPod " + str(inferredPod))

            # Update the ride with the inferred pod.
            sql = """
UPDATE {0} SET "inferredPod" = '{1}', "inferredPodName" = '{2}'
  WHERE "rideId" = '{3}';
            """.format(CibicResources.Postgres.Rides, inferredPod, inferredPodName,
                       rideId)
            #debug cur.execute(sql)

        conn.commit()
        cur.close()
    except:
        err = reportError()
        print('caught exception:', sys.exc_info()[0])
        return lambdaReply(420, str(err))

    return processedReply()

def getPointLeaveTime(cur, rideId, lat, lon):
    """
    Get the waypoints for the ride and return the time when leaving the point
    defined by lat, lon.
    """
    print("Debug lat " + str(lat) + " lon " + str(lon))
    # Get the waypoints which are 'close' to the point.
#    sql = """
#SELECT pod, "podName", "flowJoinPointsJson"
#  FROM {0}
#  WHERE role = 'steward' AND flow = '{1}' AND region = '{2}' AND organization = '{3}' AND
#        "endTime" > '{4}' AND "startTime" < '{5}';
#    """.format(CibicResources.Postgres.WaypointsRaw)
#    cur.execute(sql)
#    stewardRides = cur.fetchall()
