import os
import sys
import csv
import random

# ==================================================
# SUMO SETUP
# ==================================================

if 'SUMO_HOME' in os.environ:
    tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
    sys.path.append(tools)
else:
    sys.exit("Please set the SUMO_HOME environment variable.")

import traci

# ==================================================
# OUTPUT FOLDER
# ==================================================

os.makedirs("output", exist_ok=True)

csv_file_path = os.path.join(
    "output",
    "vehicle_charge_levels.csv"
)

station_capacity_csv_path = os.path.join(
    "output",
    "station_capacity.csv"
)

log_file_path = os.path.join(
    "output",
    "simulation_log.txt"
)

capacity_log_path = os.path.join(
    "output",
    "station_capacity_updated.txt"
)

# ==================================================
# START SUMO
# ==================================================

sumoCmd = [
    "sumo-gui",
    "-c",
    "gothamcity.sumocfg"
]

traci.start(sumoCmd)

# ==================================================
# GLOBAL VARIABLES
# ==================================================

stationWithCapacity = {}

total_energy_used = 0
total_charging_events = 0

# ==================================================
# FILE UTILITIES
# ==================================================

def write_to_csv(data, filename):

    with open(filename, mode='a', newline='') as file:

        writer = csv.writer(file)

        if file.tell() == 0:
            writer.writerow([
                'Step',
                'Vehicle_ID',
                'Battery_Level'
            ])

        writer.writerows(data)


def log_to_file(message, filename):

    with open(filename, mode='a') as file:
        file.write(message + '\n')


# ==================================================
# CHARGING STATION FUNCTIONS
# ==================================================

def initializeStations():

    stations = traci.chargingstation.getIDList()

    for station in stations:
        stationWithCapacity[station] = 0

    print("Stations Initialized")


def getDistance(vehicleID, stationID):

    try:

        carPosition = traci.vehicle.getLanePosition(vehicleID)

        carLane = traci.vehicle.getLaneID(vehicleID)

        carEdge = traci.lane.getEdgeID(carLane)

        stationLane = traci.chargingstation.getLaneID(stationID)

        stationEdge = traci.lane.getEdgeID(stationLane)

        startPos = traci.chargingstation.getStartPos(stationID)

        distance = traci.simulation.getDistanceRoad(
            carEdge,
            carPosition,
            stationEdge,
            startPos,
            isDriving=True
        )

        return distance

    except:
        return 999999


def isAvailable(stationID):

    if stationWithCapacity[stationID] < 2:
        stationWithCapacity[stationID] += 1
        return True

    return False


def findBestStation(vehicleID):

    stationList = traci.chargingstation.getIDList()

    bestStation = None
    bestScore = float('inf')

    for station in stationList:

        distance = getDistance(vehicleID, station)

        queueLength = stationWithCapacity[station]

        score = (0.7 * distance) + (0.3 * queueLength)

        if score < bestScore:

            bestScore = score

            bestStation = station

    return bestStation


def rerouteToStation(vehicleID):

    global total_charging_events

    stationID = findBestStation(vehicleID)

    if stationID is None:
        return

    stationLane = traci.chargingstation.getLaneID(stationID)

    stationEdge = traci.lane.getEdgeID(stationLane)

    traci.vehicle.changeTarget(
        vehicleID,
        stationEdge
    )

    traci.vehicle.setChargingStationStop(
        vehicleID,
        stationID
    )

    stationWithCapacity[stationID] += 1

    total_charging_events += 1

    log_to_file(
        f"Vehicle {vehicleID} assigned to {stationID}",
        log_file_path
    )


def releaseStation(vehicleID):

    stations = traci.chargingstation.getIDList()

    for station in stations:

        vehicles = traci.chargingstation.getVehicleIDs(station)

        if vehicleID in vehicles:

            stationWithCapacity[station] = max(
                0,
                stationWithCapacity[station] - 1
            )

            break


# ==================================================
# VEHICLE CREATION
# ==================================================

def createTraffic(numVehicles):

    routeID = "ev_route"

    try:

        edgeList = traci.edge.getIDList()

        if len(edgeList) >= 2:

            traci.route.add(
                routeID=routeID,
                edges=[edgeList[0], edgeList[1]]
            )

            for i in range(numVehicles):

                vehID = f"EV_{i}"

                traci.vehicle.add(
                    vehID=vehID,
                    routeID=routeID,
                    depart=i * 5
                )

                battery = random.randint(50, 100)

                traci.vehicle.setParameter(
                    vehID,
                    "battery",
                    str(battery)
                )

    except Exception as e:

        print("Vehicle creation error:", e)


# ==================================================
# BATTERY SIMULATION
# ==================================================

def batterySimulation(step):

    global total_energy_used

    vehicles = traci.vehicle.getIDList()

    for vehicle in vehicles:

        battery = float(
            traci.vehicle.getParameter(
                vehicle,
                "battery"
            ) or 100
        )

        speed = traci.vehicle.getSpeed(vehicle)

        if traci.vehicle.isStopped(vehicle):

            battery += 2

            if battery >= 80:

                battery = 80

                releaseStation(vehicle)

                traci.vehicle.resume(vehicle)

                log_to_file(
                    f"{vehicle} charging completed",
                    log_file_path
                )

        else:

            consumption = max(
                1,
                int(speed / 10)
            )

            battery -= consumption

            total_energy_used += consumption

        battery = max(0, min(100, battery))

        traci.vehicle.setParameter(
            vehicle,
            "battery",
            str(battery)
        )

        write_to_csv(
            [[step, vehicle, battery]],
            csv_file_path
        )

        if battery <= 30:

            if not traci.vehicle.isStopped(vehicle):

                rerouteToStation(vehicle)

                log_to_file(
                    f"{vehicle} battery low ({battery:.1f}%)",
                    log_file_path
                )

# ==================================================
# WRITE STATION CAPACITY
# ==================================================

def writeCapacity(step):

    with open(
        station_capacity_csv_path,
        mode='a',
        newline=''
    ) as file:

        writer = csv.writer(file)

        if file.tell() == 0:

            writer.writerow([
                "Step",
                "Station_ID",
                "Vehicles"
            ])

        for station, count in stationWithCapacity.items():

            writer.writerow([
                step,
                station,
                count
            ])


# ==================================================
# MAIN SIMULATION
# ==================================================

step = 0

while step < 10:
    traci.simulationStep()
    step += 1

initializeStations()

createTraffic(20)

MAX_STEPS = 5000

while step < MAX_STEPS:

    traci.simulationStep()

    if step % 2 == 0:

        batterySimulation(step)

        writeCapacity(step)

    step += 1

# ==================================================
# RESULTS
# ==================================================

print("\n================================")
print("SIMULATION COMPLETED")
print("================================")

print(f"Total Energy Used : {total_energy_used}")

print(f"Charging Events   : {total_charging_events}")

print(f"Stations          : {len(stationWithCapacity)}")

print("Logs saved in output folder.")

traci.close()