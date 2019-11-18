import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.cm as cm
from Utils.OccupancyGrid import OccupancyGrid
from scipy.ndimage import gaussian_filter
import math


class ScanMatcher:
    def __init__(self, og, coarseOG, searchRadius, searchHalfRad, scanSigmaInNumGrid, coarseFactor):
        self.searchRadius = searchRadius
        self.searchHalfRad = searchHalfRad
        self.og = og
        self.coarseOG = coarseOG
        self.scanSigmaInNumGrid = scanSigmaInNumGrid
        self.coarseFactor = coarseFactor

    def frameSearchSpace(self, estimatedX, estimatedY, unitLength, sigma):
        maxScanRadius = 1.1 * self.og.lidarMaxRange + self.searchRadius
        xRangeList = [estimatedX - maxScanRadius, estimatedX + maxScanRadius]
        yRangeList = [estimatedY - maxScanRadius, estimatedY + maxScanRadius]
        self.og.checkAndExapndOG(xRangeList, yRangeList)
        occuProbSP = self.extractOG(xRangeList, yRangeList, 1, unitLength, sigma)
        emptyProbSP = self.extractOG(xRangeList, yRangeList, 0, unitLength, sigma)
        return xRangeList, yRangeList, occuProbSP, emptyProbSP

    def extractOG(self, xRangeList, yRangeList, threshold, unitLength, sigma):
        idxEndX, idxEndY = int((xRangeList[1] - xRangeList[0]) / unitLength), int((yRangeList[1] - yRangeList[0]) / unitLength)
        searchSpace = math.log(0.01) * np.ones((idxEndY + 1, idxEndX + 1))
        xRangeListIdx, yRangeListIdx = self.og.convertRealXYToMapIdx(xRangeList, yRangeList)
        ogMap = self.og.occupancyGridVisited[yRangeListIdx[0]: yRangeListIdx[1], xRangeListIdx[0]: xRangeListIdx[1]] / \
                self.og.occupancyGridTotal[yRangeListIdx[0]: yRangeListIdx[1], xRangeListIdx[0]: xRangeListIdx[1]]
        ogX = self.og.OccupancyGridX[yRangeListIdx[0]: yRangeListIdx[1], xRangeListIdx[0]: xRangeListIdx[1]]
        ogY = self.og.OccupancyGridY[yRangeListIdx[0]: yRangeListIdx[1], xRangeListIdx[0]: xRangeListIdx[1]]
        ogMapOccu = ogMap > 0.5
        ogXOccu, ogYOccu = ogX[ogMapOccu], ogY[ogMapOccu]
        ogIdxOccu = self.convertXYToSearchSpaceIdx(ogXOccu, ogYOccu, xRangeList[0], yRangeList[0], unitLength)
        ogMapEmpty = ogMap < 0.5
        ogXEmpty, ogYEmpty = ogX[ogMapEmpty], ogY[ogMapEmpty]
        ogIdxEmpty = self.convertXYToSearchSpaceIdx(ogXEmpty, ogYEmpty, xRangeList[0], yRangeList[0], unitLength)
        if threshold > 0.5:
            searchSpace[ogIdxEmpty[1], ogIdxEmpty[0]] = math.log(0.01)
            searchSpace[ogIdxOccu[1], ogIdxOccu[0]] = math.log(1)
        else:
            searchSpace[ogIdxOccu[1], ogIdxOccu[0]] = math.log(0.01)
            searchSpace[ogIdxEmpty[1], ogIdxEmpty[0]] = math.log(1)
        probSP = self.generateProbSearchSpace(searchSpace, sigma)
        return probSP

    def generateProbSearchSpace(self, searchSpace, sigma):
        probSP = gaussian_filter(searchSpace, sigma=sigma)
        #maxCap = 1 / (2 * np.pi * sigma ** 2)
        #probSP[probSP > maxCap] = maxCap
        #probSP = probSP / maxCap
        return probSP

    def matchScan(self, reading, count):
        """Iteratively find the best dx, dy and dtheta"""
        estimatedX, estimatedY, estimatedTheta, rMeasure = reading['x'], reading['y'], reading['theta'], reading['range']

        if count == 1:
            return reading
        # Coarse Search
        courseSearchStep = self.coarseFactor * self.og.unitGridSize  # make this even number of unitGridSize for performance
        coarseSigma = self.scanSigmaInNumGrid / self.coarseFactor
        xRangeList, yRangeList, occuProbSP, emptyProbSP = self.frameSearchSpace(estimatedX, estimatedY, courseSearchStep, coarseSigma)
        matchedPx, matchedPy, matchedReading = self.searchToMatch(
            occuProbSP, emptyProbSP, reading, xRangeList, yRangeList, self.searchRadius, self.searchHalfRad, courseSearchStep, count)
        #########   For Debug Only  #############
        if count > 0:
            self.plotMatchOverlay(occuProbSP, matchedPx, matchedPy, matchedReading, xRangeList, yRangeList, courseSearchStep)
            self.plotMatchOverlay(emptyProbSP, matchedPx, matchedPy, matchedReading, xRangeList, yRangeList, courseSearchStep)
        #########################################
        # Fine Search
        fineSearchStep = self.og.unitGridSize
        fineSigma = self.scanSigmaInNumGrid
        fineSearchHalfRad = self.searchHalfRad
        xRangeList, yRangeList, occuProbSP, emptyProbSP = self.frameSearchSpace(matchedReading['x'], matchedReading['y'], fineSearchStep, fineSigma)
        matchedPx, matchedPy, matchedReading = self.searchToMatch(
            occuProbSP, emptyProbSP, matchedReading, xRangeList, yRangeList, courseSearchStep, fineSearchHalfRad, fineSearchStep, count)
        #########   For Debug Only  #############
        if count > 0:
            self.plotMatchOverlay(occuProbSP - emptyProbSP, matchedPx, matchedPy, matchedReading, xRangeList, yRangeList, fineSearchStep)
        #########################################
        return matchedReading

    def covertMeasureToXY(self, estimatedX, estimatedY, estimatedTheta, rMeasure):
        rads = np.linspace(estimatedTheta - self.og.lidarFOV / 2, estimatedTheta + self.og.lidarFOV / 2,
                           num=self.og.numSamplesPerRev)
        range_idx = rMeasure < self.og.lidarMaxRange
        rMeasureInRange = rMeasure[range_idx]
        rads = rads[range_idx]
        px = estimatedX + np.cos(rads) * rMeasureInRange
        py = estimatedY + np.sin(rads) * rMeasureInRange
        return px, py

    def searchToMatch(self, occuProbSP, emptyProbSP, reading, xRangeList, yRangeList, searchRadius, searchHalfRad, unitLength, count):
        estimatedX, estimatedY, estimatedTheta, rMeasure = reading['x'], reading['y'], reading['theta'], reading['range']
        rMeasure = np.asarray(rMeasure)
        px, py = self.covertMeasureToXY(estimatedX, estimatedY, estimatedTheta, rMeasure)
        numCellOfSearchRadius  = int(searchRadius / unitLength)
        xMovingRange = np.arange(-numCellOfSearchRadius, numCellOfSearchRadius + 1)
        yMovingRange = np.arange(-numCellOfSearchRadius, numCellOfSearchRadius + 1)
        xv, yv = np.meshgrid(xMovingRange, yMovingRange)
        xv = xv.reshape((xv.shape[0], xv.shape[1], 1))
        yv = yv.reshape((yv.shape[0], yv.shape[1], 1))
        maxMatchScore, maxIdx = float("-inf"), None
        for theta in np.arange(-searchHalfRad, searchHalfRad + self.og.angularStep, self.og.angularStep):
            # EmptyZone result
            emptyX, emptyY, occupiedX, occupiedY = self.coarseOG.updateOccupancyGrid(reading, theta, update=False)
            emptyXIdx, emptyYIdx = self.convertXYToSearchSpaceIdx(emptyX, emptyY, xRangeList[0], yRangeList[0], unitLength)

            uniqueRotatedPxPyIdx = np.unique(np.column_stack((emptyXIdx, emptyYIdx)), axis=0)
            emptyXIdx, emptyYIdx = uniqueRotatedPxPyIdx[:, 0], uniqueRotatedPxPyIdx[:, 1]
            #########   For Debug Only  #############
            #self.plotMatchOverlay(emptyProbSP, emptyX, emptyY, reading, xRangeList, yRangeList, unitLength)
            #########################################
            emptyXIdx = emptyXIdx.reshape(1, 1, -1)
            emptyYIdx = emptyYIdx.reshape(1, 1, -1)
            emptyXIdx = emptyXIdx + xv
            emptyYIdx = emptyYIdx + yv
            convEmptyResult = emptyProbSP[emptyYIdx, emptyXIdx]
            convEmptyResultSum = np.sum(convEmptyResult, axis=2)
            convEmptyResultSum = convEmptyResultSum
            # OccupiedZone result
            occupiedXIdx, occupiedYIdx = self.convertXYToSearchSpaceIdx(occupiedX, occupiedY, xRangeList[0], yRangeList[0], unitLength)

            uniqueRotatedPxPyIdx = np.unique(np.column_stack((occupiedXIdx, occupiedYIdx)), axis=0)
            occupiedXIdx, occupiedYIdx = uniqueRotatedPxPyIdx[:, 0], uniqueRotatedPxPyIdx[:, 1]
            occupiedXIdx = occupiedXIdx.reshape(1, 1, -1)
            occupiedYIdx = occupiedYIdx.reshape(1, 1, -1)
            occupiedXIdx = occupiedXIdx + xv
            occupiedYIdx = occupiedYIdx + yv
            convOccupiedResult = occuProbSP[occupiedYIdx, occupiedXIdx]
            convOccupiedResultSum = np.sum(convOccupiedResult, axis=2)
            convOccupiedResultSum = convOccupiedResultSum
            convResultSum = convEmptyResultSum + convOccupiedResultSum
            if convResultSum.max() > maxMatchScore:
                maxMatchScore = convResultSum.max()
                maxIdx = np.unravel_index(convResultSum.argmax(), convResultSum.shape)
                dTheta = theta
                #########   For Debug Only  #############
                if count > 1:
                    matchedPx, matchedPy = self.rotate((estimatedX, estimatedY), (occupiedX, occupiedY), dTheta)
                    dx, dy = xMovingRange[maxIdx[1]] * unitLength, yMovingRange[maxIdx[0]] * unitLength
                    #self.plotMatchOverlay(occuProbSP, matchedPx + dx, matchedPy + dy, reading, xRangeList, yRangeList, unitLength)
                    a = 1
                    matchedPx, matchedPy = self.rotate((estimatedX, estimatedY), (emptyX, emptyY), dTheta)
                    dx, dy = xMovingRange[maxIdx[1]] * unitLength, yMovingRange[maxIdx[0]] * unitLength
                    self.plotMatchOverlay(emptyProbSP, matchedPx + dx, matchedPy + dy, reading, xRangeList, yRangeList, unitLength)
                    a = 1
                ########################################
        if maxIdx is None:
            dx, dy, dTheta = 0, 0, 0
        else:
            dx, dy = xMovingRange[maxIdx[1]] * unitLength, yMovingRange[maxIdx[0]] * unitLength
        matchedReading = {"x": estimatedX + dx, "y": estimatedY + dy, "theta": estimatedTheta + dTheta,
                          "range": rMeasure}
        matchedPx, matchedPy = self.rotate((estimatedX, estimatedY), (px, py), dTheta)
        return matchedPx + dx, matchedPy + dy, matchedReading

    def plotMatchOverlay(self, probSP, matchedPx, matchedPy, matchedReading, xRangeList, yRangeList, unitLength):
        plt.figure(figsize=(19.20, 19.20))
        plt.imshow(probSP, origin='lower')
        pxIdx, pyIdx = self.convertXYToSearchSpaceIdx(matchedPx, matchedPy, xRangeList[0], yRangeList[0], unitLength)
        plt.scatter(pxIdx, pyIdx, c='r', s=5)
        #poseXIdx, poseYIdx = self.convertXYToSearchSpaceIdx(matchedReading['x'], matchedReading['y'], xRangeList[0], yRangeList[0], unitLength)
        #plt.scatter(poseXIdx, poseYIdx, color='blue', s=50)
        plt.show()

    def rotate(self, origin, point, angle):
        """
        Rotate a point counterclockwise by a given angle around a given origin.

        The angle should be given in radians.
        """
        ox, oy = origin
        px, py = point
        qx = ox + np.cos(angle) * (px - ox) - np.sin(angle) * (py - oy)
        qy = oy + np.sin(angle) * (px - ox) + np.cos(angle) * (py - oy)
        return qx, qy

    def convertXYToSearchSpaceIdx(self, px, py, beginX, beginY, unitLength):
        xIdx = (((px - beginX) / unitLength)).astype(int)
        yIdx = (((py - beginY) / unitLength)).astype(int)
        return xIdx, yIdx

def updateEstimatedPose(currentRawReading, previousMatchedReading, previousRawReading):
    estimatedX = previousMatchedReading['x'] + currentRawReading['x'] - previousRawReading['x']
    estimatedY = previousMatchedReading['y'] + currentRawReading['y'] - previousRawReading['y']
    estimatedTheta = previousMatchedReading['theta'] + currentRawReading['theta'] - previousRawReading['theta']
    estimatedReading = {'x': estimatedX, 'y': estimatedY, 'theta': estimatedTheta, 'range': currentRawReading['range']}
    return estimatedReading

def updateTrajectoryPlot(matchedReading, xTrajectory, yTrajectory, colors, count):
    x, y, theta, range = matchedReading['x'], matchedReading['y'], matchedReading['theta'], matchedReading['range']
    xTrajectory.append(x)
    yTrajectory.append(y)
    if count % 1 == 0:
        plt.scatter(x, y, color=next(colors), s=35)

def processSensorData(sensorData, og, sm, plotTrajectory = True):
    count = 0
    plt.figure(figsize=(19.20, 19.20))
    colors = iter(cm.rainbow(np.linspace(1, 0, len(sensorData) + 1)))
    xTrajectory, yTrajectory = [], []
    for key in sorted(sensorData.keys()):
        count += 1
        print(count)
        if count == 1:
            og.updateOccupancyGrid(sensorData[key])
            previousMatchedReading = sensorData[key]
            previousRawReading = sensorData[key]
        estimatedReading = updateEstimatedPose(sensorData[key], previousMatchedReading, previousRawReading)
        matchedReading = sm.matchScan(estimatedReading, count)
        og.updateOccupancyGrid(matchedReading)
        # og.plotOccupancyGrid(plotThreshold=False)
        previousMatchedReading = matchedReading
        previousRawReading = sensorData[key]

        if count == 100:
            break
        if plotTrajectory:
            updateTrajectoryPlot(matchedReading, xTrajectory, yTrajectory, colors, count)
    if plotTrajectory:
        plt.scatter(xTrajectory[0], yTrajectory[0], color='r', s=500)
        plt.scatter(xTrajectory[-1], yTrajectory[-1], color=next(colors), s=500)
    plt.plot(xTrajectory, yTrajectory)
    og.plotOccupancyGrid(plotThreshold=False)

def main():
    initMapXLength, initMapYLength, unitGridSize, lidarFOV, lidarMaxRange = 10, 10, 0.02, np.pi, 10 # in Meters
    scanMatchSearchRadius, scanMatchSearchHalfRad, scanSigmaInNumGrid, coarseFactor = 2.2, 0.35, 2, 10 # 0.35 is 20deg
    wallThickness = 3 * unitGridSize
    jsonFile = "../DataSet/PreprocessedData/intel_gfs"
    with open(jsonFile, 'r') as f:
        input = json.load(f)
        sensorData = input['map']
    numSamplesPerRev = len(sensorData[list(sensorData)[0]]['range'])  # Get how many points per revolution
    spokesStartIdx = int(0) # theta= 0 is x direction. spokes=0 is -y direction, the first ray of lidar scan direction. spokes increase counter-clockwise

    coarseFactor = 5
    og = OccupancyGrid(initMapXLength, initMapYLength, unitGridSize, lidarFOV, numSamplesPerRev, lidarMaxRange, wallThickness, spokesStartIdx)
    coarseOG = OccupancyGrid(initMapXLength, initMapYLength, coarseFactor * unitGridSize, lidarFOV, numSamplesPerRev, lidarMaxRange, coarseFactor * wallThickness, spokesStartIdx)
    sm = ScanMatcher(og, coarseOG, scanMatchSearchRadius, scanMatchSearchHalfRad, scanSigmaInNumGrid, coarseFactor)
    processSensorData(sensorData, og, sm, plotTrajectory=False)

if __name__ == '__main__':
    main()