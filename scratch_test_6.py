import pyvista as pv
import numpy as np

plotter = pv.Plotter(off_screen=True)
mesh = pv.Sphere()
plotter.add_mesh(mesh)
plotter.open_movie("test_movie.mp4")
plotter.write_frame()
try:
    plotter.mwriter.close()
    print("mwriter.close() succeeded")
except AttributeError:
    print("plotter has no mwriter")
plotter.close()
