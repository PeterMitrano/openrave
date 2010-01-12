#!/usr/bin/env python
# Copyright (C) 2009-2010 Rosen Diankov (rosen.diankov@gmail.com)
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License. 
from __future__ import with_statement # for python 2.5

from openravepy import *
from openravepy.examples import ReachabilityModel
from numpy import *
import time,pickle
from optparse import OptionParser
from itertools import izip

class InverseReachabilityModel(OpenRAVEModel):
    def __init__(self,robot):
        OpenRAVEModel.__init__(self,robot=robot)
        self.reachability = ReachabilityModel(robot=robot)
        if not self.reachability.load():
            self.reachability.autogenerate()

    def has(self):
        return len(self.reachabilitydensity3d) > 0

    def load(self):
        params = OpenRAVEModel.load(self)
        if params is None:
            return False
        self.reachabilitystats,self.reachabilitydensity3d,self.pointscale = params
        return self.has()

    def save(self):
        OpenRAVEModel.save(self,(self.reachabilitystats,self.reachabilitydensity3d,self.pointscale))

    def getfilename(self):
        return os.path.join(OpenRAVEModel.getfilename(self),'reachability.' + self.manip.GetName() + '.pp')

    def generateFromOptions(self,options):
        self.generate(xyzthresh=options.xyzthresh,rotthresh=options.rotthresh)

    def generate(self,heightthresh=0.05,rotthresh=0.25):
        # find the density
        basetrans = c_[invertPoses(self.reachability.reachabilitystats[:,0:7]),self.reachability.reachabilitystats[:,7:]]
        if basetrans.shape[1] < 8:
            basetrans = c_[basetrans,ones(basetrans.shape[0])]
        # find the density of the points
        searchtrans = c_[basetrans[:,0:4],(rotthresh/heightthresh)*basetrans[:,6:7]]
        kdtree = pyANN.KDTree(searchtrans)
        transdensity = kdtree.kFRSearchArray(searchtrans,0.25*rotthresh**2,0,rotthresh*0.2)[2]
        basetrans = basetrans[argsort(-transdensity),:]
        
        # find all equivalence classes
        quatrolls = array([quatFromAxisAngle(array((0,0,1)),roll) for roll in arange(0,2*pi,pi/32)])
        equivalenceclasses = []
        while len(basetrans) > 0:
            print len(basetrans)
            searchtrans = c_[basetrans[:,0:4],(rotthresh/heightthresh)*basetrans[:,6:7]]
            kdtree = pyANN.KDTree(searchtrans)
            p = searchtrans[0]
            foundindices = zeros(len(searchtrans),bool)
            querypoints = c_[self.quatMultArrayT(p[0:4],quatrolls),tile(p[4:],(len(quatrolls),1))]
            for querypoint in querypoints:
                k = min(len(searchtrans),1000)
                neighs,dists,kball = kdtree.kFRSearch(querypoint,rotthresh**2,k,rotthresh*0.01)
                if k < kball:
                    neighs,dists,kball = kdtree.kFRSearch(querypoint,rotthresh**2,kball,rotthresh*0.01)
                foundindices[neighs] = True
            equivalenttrans = basetrans[flatnonzero(foundindices),:]
            basetrans = basetrans[flatnonzero(foundindices==False),:]
            
            # for all the equivalent rotations, find the extract rotation about z that minimizes the distance between the root
            cosangs = -p[0]*equivalenttrans[:,3]-p[1]*equivalenttrans[:,2]+p[2]*equivalenttrans[:,1]+p[3]*equivalenttrans[:,0]
            sinangs = p[0]*equivalenttrans[:,0]+p[1]*equivalenttrans[:,1]+p[2]*equivalenttrans[:,2]+p[3]*equivalenttrans[:,3]
            ilengthsq = 1.0/(cosangs**2+sinangs**2)
            zz = sinangs**2 * ilengthsq
            zw = cosangs*sinangs*ilengthsq
            finaltrans = c_[cosangs*equivalenttrans[:,0]-sinangs*equivalenttrans[:,3],
                            cosangs*equivalenttrans[:,1]-sinangs*equivalenttrans[:,2],
                            cosangs*equivalenttrans[:,2]-sinangs*equivalenttrans[:,1],
                            cosangs*equivalenttrans[:,3]-sinangs*equivalenttrans[:,0],
                            2.0*((0.5-zz)*equivalenttrans[:,4]-zw*equivalenttrans[:,5]),
                            2.0*((0.5-zz)*equivalenttrans[:,4]-zw*equivalenttrans[:,5]),
                            equivalenttrans[:,6]]
            # make sure all quaternions are on the same hemisphere
            
            equivalenceclasses.append(finaltrans)
            del kdtree

    def autogenerate(self,forcegenerate=True):
        # disable every body but the target and robot
        bodies = [b for b in self.env.GetBodies() if b.GetNetworkId() != self.robot.GetNetworkId()]
        for b in bodies:
            b.Enable(False)
        try:
            if self.robot.GetRobotStructureHash() == '6bc480d3dd7d363ec3305fdb8437a7cc' and self.manip.GetName() == 'arm':
                self.generate(heightthresh=0.05,rotthresh=0.25)
            else:
                if not forcegenerate:
                    raise ValueError('failed to find auto-generation parameters')
                self.generate()
            self.save()
        finally:
            for b in bodies:
                b.Enable(True)

    @staticmethod
    def quatMultArrayT(q,qarray):
        """ multiplies a quaternion q with each quaternion in the Nx4 array qarray"""
        return c_[(q[0]*qarray[:,0] - q[1]*qarray[:,1] - q[2]*qarray[:,2] - q[3]*qarray[:,3],
                   q[0]*qarray[:,1] + q[1]*qarray[:,0] + q[2]*qarray[:,3] - q[3]*qarray[:,2],
                   q[0]*qarray[:,2] + q[2]*qarray[:,0] + q[3]*qarray[:,1] - q[1]*qarray[:,3],
                   q[0]*qarray[:,3] + q[3]*qarray[:,0] + q[1]*qarray[:,2] - q[2]*qarray[:,1])]
    @staticmethod
    def quatMult(q1,q2):
        return array((q1[0]*q2[0] - q1[1]*q2[1] - q1[2]*q2[2] - q1[3]*q2[3],
                      q1[0]*q2[1] + q1[1]*q2[0] + q1[2]*q2[3] - q1[3]*q2[2],
                      q1[0]*q2[2] + q1[2]*q2[0] + q1[3]*q2[1] - q1[1]*q2[3],
                      q1[0]*q2[3] + q1[3]*q2[0] + q1[1]*q2[2] - q1[2]*q2[1]))
    @staticmethod
    def CameraTransformDistSqr(q,qarray):
        """ distance between two quaternions ignoring left rotation around z axis of qarray"""
        sinang = -q[0]*qarray[3,:]-q[1]*qarray[2,:]+q[2]*qarray[1,:]+q[3]*qarray[0,:]
        cosang = q[0]*qarray[0,:]+q[1]*qarray[1,:]+q[2]*qarray[2,:]+q[3]*qarray[3,:]
        length = sqrt(sinang**2+cosang**2)
        sinang /= length
        cosang /= length
        return (q[0]-cosang*qarray[0,:]+sinang*qarray[3,:])**2 + (q[1]-cosang*qarray[1,:]+sinang*qarray[2,:])**2 + (q[2]-cosang*qarray[2,:]+sinang*qarray[1,:])**2 + (q[3]-cosang*qarray[3,:]+sinang*qarray[0,:])**2

    @staticmethod
    def CreateOptionParser():
        parser = OpenRAVEModel.CreateOptionParser()
        parser.add_option('--xyzthresh',action='store',type='float',dest='xyzdelta',default=0.02,
                          help='The max radius of the arm to perform the computation')
        parser.add_option('--rotthresh',action='store',type='float',dest='rotthresh',default=pi/16.0,
                          help='The max radius of the arm to perform the computation')
        return parser
    @staticmethod
    def RunFromParser(Model=None,parser=None):
        if parser is None:
            parser = ReachabilityModel.CreateOptionParser()
        (options, args) = parser.parse_args()
        Model = lambda robot: InverseReachabilityModel(robot=robot)
        OpenRAVEModel.RunFromParser(Model=Model,parser=parser)

if __name__ == "__main__":
    InverseReachabilityModel.RunFromParser()