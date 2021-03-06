# Port of https:#github.com/Formlabs/hackathon-slicer/blob/master/app/js/slicer.js
#
#

# internal
import struct
import math
import time
import os
import sys # for stdout

# external
import cv2
import numpy

# user
import GL_Viewport
import rleEncode
from PhotonFile import *


class GL_Stl2Slices:
    gui=False
    viewport = None

    def clearModel(self):
        self.points = []
        self.normals = []
        self.cmin = []
        self.cmax = []

    def load_binary_stl(self,filename, scale=1):
        print("Reading binary")
        # filebytes = os.path.getsize(filename)

        #scale=scale*0.1
        fp = open(filename, 'rb')

        h = fp.read(80)
        l = struct.unpack('I', fp.read(4))[0]
        count = 0

        t0 = time.time()

        self.clearModel()
        points = []
        normals = []
        filepos = 0
        while True:
            try:
                p = fp.read(12)
                if len(p) == 12:
                    n = struct.unpack('f', p[0:4])[0], struct.unpack('f', p[4:8])[0], struct.unpack('f', p[8:12])[0]

                p = fp.read(12)
                if len(p) == 12:
                    p1 = struct.unpack('f', p[0:4])[0], struct.unpack('f', p[4:8])[0], struct.unpack('f', p[8:12])[0]

                p = fp.read(12)
                if len(p) == 12:
                    p2 = struct.unpack('f', p[0:4])[0], struct.unpack('f', p[4:8])[0], struct.unpack('f', p[8:12])[0]

                p = fp.read(12)
                if len(p) == 12:
                    p3 = struct.unpack('f', p[0:4])[0], struct.unpack('f', p[4:8])[0], struct.unpack('f', p[8:12])[0]

                if len(p) == 12:
                    # switch coordinates to OpenGL
                    a = 0
                    b = 1
                    c = 2
                    n = [n[a], n[b], n[c]]
                    p1 = [p1[a], p1[b], p1[c]]
                    p2 = [p2[a], p2[b], p2[c]]
                    p3 = [p3[a], p3[b], p3[c]]

                    # add points to array
                    points.append(p1)
                    points.append(p2)
                    points.append(p3)
                    normals.append(n)

                count += 1
                fp.read(2)

                # Check if we reached end of file
                if len(p) == 0:
                    break
            except EOFError:
                break
        fp.close()

        # t1=time.time()
        # print ("t1-t0",t1-t0)

        # use numpy for easy and fast center and scale model
        np_points = numpy.array(points)
        np_normals = numpy.array(normals)

        # scale model, 1mm should be 1/0,047 pixels
        #scale=scale/0.047
        np_points = np_points * scale

        # find max and min of x, y and z
        x = np_points[:, 0]
        y = np_points[:, 1]
        z = np_points[:, 2]
        self.cmin = (x.min(), y.min(), z.min())
        self.cmax = (x.max(), y.max(), z.max())
        self.modelheight = self.cmax[2] - self.cmin[2]
        #print ("min: ",self.cmin)
        #print ("max: ",self.cmax)

        # Center model and put on base
        #trans = [0, 0, 0]
        #trans[0] = -(self.cmax[0] - self.cmin[0]) / 2 - self.cmin[0]
        #trans[1] = -(self.cmax[2] - self.cmin[2]) / 2 - self.cmin[2]
        #trans[2] = -self.cmin[1]

        # We want the model centered in 2560x1440
        # 2560x1440 pixels equals 120x67
        #trans[0] = trans[0] +1440 / 2
        #trans[2] = trans[2] +2560 / 2

        # Center numpy array of points which is returned for fast OGL model loading
        #np_points = np_points + trans

        # Find bounding box again
        x = np_points[:, 0]
        y = np_points[:, 1]
        z = np_points[:, 2]
        self.cmin = (x.min(), y.min(), z.min())
        self.cmax = (x.max(), y.max(), z.max())

        # align coordinates on grid
        # this will reduce number of points and speed up loading
        # with benchy grid-screenres/1:  total time 28 sec, nr points remain 63k , but large artifacts
        # with benchy grid-screenres/50: total time 39 sec, nr points remain 112k, no artifacts
        # w/o benchy :                   total time 40 sec, nr points remain 113k, no artifacts
        #screenres = 0.047
        #grid = screenres / 50  # we do not want artifacts but reduce rounding errors in the file to cause misconnected triangles
        #np_points = grid * (np_points // grid)


        # return points and normal for OGLEngine to display
        return np_points, np_normals

    def __init__(self, stlfilename, scale=1,
                 outputpath=None,       # should end with '/'
                 layerheight=0.05,
                 photonfilename=None,   # keep outputpath=None if output to photonfilename
                 normalexposure=8.0,
                 bottomexposure=90,
                 bottomlayers=8,
                 offtime=6.5,
                 ):

        self.viewport = GL_Viewport.Viewport()

        # Get path of script/exe for local resources like iconpath and newfile.photon
        if getattr(sys, 'frozen', False):# frozen
            self.installpath = os.path.dirname(sys.executable)
        else: # unfrozen
            self.installpath = os.path.dirname(os.path.realpath(__file__))

        # Measure how long it takes
        t1 = time.time()

        # Setup output path
        if outputpath==None and photonfilename==None:return

        #create path if not exists
        if not outputpath==None:
            if not os.path.exists(outputpath):
                os.makedirs(outputpath)

        # if we output to PhotonFile we need a place to store RunLengthEncoded images
        if not photonfilename==None:
            rlestack=[]

        # Load 3d Model in memory
        points, normals = self.load_binary_stl(stlfilename, scale=scale)

        # Check if inside build area
        size=(self.cmax[0]-self.cmin[0],self.cmax[1]-self.cmin[1],self.cmax[2]-self.cmin[2])
        if size[0]>65 or size[1]>115:
           sizestr="("+str(int(size[0]))+"x"+str(int(size[2]))+")"
           areastr="(65x115)"
           errmsg="Model is too big "+sizestr+" for build area "+areastr+". Maybe try another orientation, use the scale argument (-s or --scale) or cut up the model."
           if not self.gui: 
              print (errmsg)
           else:
              sys.tracebacklimit = None
              raise Exception(errmsg)
              sys.tracebacklimit = 0
           sys.exit() # quit() does not work if we make this an exe with cx_Freeze
    

        # Load mesh
        #print ("loading mesh")
        self.viewport.loadMesh(points,normals,self.cmin,self.cmax);
        #self.viewport.display() # this will loop until window is closed
        self.viewport.draw()

        microns = layerheight*1000 #document.getElementById("height").value;
        bounds = self.viewport.getBounds()
        #print ((bounds['zmax']-bounds['zmin']) , self.viewport.printer.getGLscale())
        #quit()
        zrange_mm=(bounds['zmax']-bounds['zmin']) / self.viewport.printer.getGLscale()
        count=math.ceil(zrange_mm * 1000 / microns);        
        #print ("b",bounds)
        #print ("z",zrange_mm)
        #print ("m",microns)
        #print ("c",count)
 
        if not photonfilename==None:
            rlestack=[]

        for i in range(0,count):
            data = self.viewport.getSliceAt(i / count)
            img=data.reshape(2560,1440,4)
            imgarr8=img[:,:,1]
            if photonfilename==None:            
	            Sstr = "%04d" % i
	            filename = outputpath+Sstr + ".png"            
	            print (i,"/",count,filename)
	            cv2.imwrite(filename, imgarr8)  
            else:
                img1D=imgarr8.flatten(0)
                rlestack.append(rleEncode.encodedBitmap_Bytes_numpy1DBlock(img1D))


        if not photonfilename==None:
            tempfilename=os.path.join(self.installpath,"newfile.photon")
            photonfile=PhotonFile(tempfilename)
            photonfile.readFile()
            photonfile.Header["Layer height (mm)"]= PhotonFile.float_to_bytes(layerheight)
            photonfile.Header["Exp. time (s)"]    = PhotonFile.float_to_bytes(normalexposure)
            photonfile.Header["Exp. bottom (s)"]  = PhotonFile.float_to_bytes(bottomexposure)
            photonfile.Header["# Bottom Layers"]  = PhotonFile.int_to_bytes(bottomlayers)
            photonfile.Header["Off time (s)"]     = PhotonFile.float_to_bytes(offtime)
            photonfile.replaceBitmaps(rlestack)
            photonfile.writeFile(photonfilename)

        print("Elapsed: ", "%.2f" % (time.time() - t1), "secs")