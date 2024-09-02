import os
import os.path as osp

import numpy as np
from osgeo import gdal
from tqdm import tqdm
from matplotlib.pyplot import figure, imshow, colorbar, show
gdal.UseExceptions()

def array_to_raster(array, geoTransform, projection, filename, resample=True):
    if resample:
        np.nan_to_num(array, copy=False, nan=-2, posinf=-2, neginf=-2)
        array = np.round(array * 10000).astype('int16')
        dtype = gdal.GDT_Int16
    else:
        dtype = gdal.GDT_Float32
    pixels_x = array.shape[1]
    pixels_y = array.shape[0]
    driver = gdal.GetDriverByName('GTiff')
    dataset = driver.Create(
        filename,
        pixels_x,
        pixels_y,
        1,
        dtype,
        options=['COMPRESS=ZSTD'])
    dataset.SetGeoTransform(geoTransform)
    dataset.SetProjection(projection)
    dataset.GetRasterBand(1).WriteArray(array)
    dataset.FlushCache() 
    del dataset

def compute_nbr(band1, band2):
    num = band1 - band2
    denom = band1 + band2
    denom[np.where(denom==0)] = np.nan
    nbr = num / denom
    return nbr

def create_nbr_raster(band1_filepath, band2_filepath, nbr_filepath):
    if osp.exists(nbr_filepath):
        print(f'file {nbr_filepath} already exists')
    ## open B5, B7, and get data
    img =  gdal.Open(band1_filepath)
    band1_data = np.array(img.GetRasterBand(1).ReadAsArray())
    crs = img.GetProjection()
    geoTransform = img.GetGeoTransform()
    # targetprj = osr.SpatialReference(wkt = img.GetProjection())
    img =  gdal.Open(band2_filepath)
    band2_data = np.array(img.GetRasterBand(1).ReadAsArray())
    del img
    # compute NBR and manage memory
    nbr_data = compute_nbr(band1_data.astype('float'), band2_data.astype('float'))
    del band1_data
    del band2_data
    # write to file
    array_to_raster(nbr_data, geoTransform, crs, nbr_filepath)

def create_nbr_rasters(data_directory, band_filenames):
    nbr = 'NBR'
    nbr_directory = osp.join(data_directory, nbr)
    if osp.exists(nbr_directory):
        print(f'directory {nbr_directory} already exists')
    else:
        os.makedirs(nbr_directory)
        print(f'successfully created directory {nbr_directory}')
    bands = list(band_filenames.keys())

    for band in bands:
        if band not in os.listdir(data_directory):
            print(f'\ndirectory {osp.join(data_directory, band)} does not exist')
            return
        
    print(f'\ncomputing NBR...')
    for full_filename in tqdm(os.listdir(osp.join(data_directory, bands[0]))):
        file_stem = full_filename[:-6]+'{0}.TIF' 
        nbr_filename = file_stem.format('NBR')
        nbr_filepath = osp.join(nbr_directory, nbr_filename)
        if osp.exists(nbr_filepath):
            print(f'file {nbr_filepath} already exists')
            continue
        band_filepaths = [
            osp.join(data_directory, band, file_stem.format(band))
            for band in bands
        ]
        create_nbr_raster(*band_filepaths, nbr_filepath)
    print(f'\nNBR files successfully written to {nbr_directory}')
    return nbr_directory

def reproject_raster(input_filepath, output_filepath=None, crs='EPSG:4326'):
    if not output_filepath:
        input_directory = osp.dirname(input_filepath)
        input_filename = osp.basename(input_filepath)
        output_filepath = osp.join(input_directory, 'reprojected_'+input_filename)
    if osp.exists(output_filepath):
        print(f'file {output_filepath} already exists')
        return output_filepath
    input_raster = gdal.Open(input_filepath)
    band = input_raster.GetRasterBand(1)
    nodata_value = band.GetNoDataValue()
    if nodata_value is None:
        nodata_value = -20000 # this is the standard for USGS NBR
    del input_raster
    gdal.Warp(
        output_filepath,
        input_filepath, 
        dstSRS=crs, 
        dstNodata = nodata_value, 
        srcNodata = nodata_value, 
        options=['-co', 'COMPRESS=ZSTD']
    )
    return output_filepath

def reproject_directory(directory, reprojection_directory=None, crs='EPSG:4326'):
    if not reprojection_directory:
        parent_directory = osp.dirname(directory)
        directory_name = osp.basename(directory)
        reprojection_directory = osp.join(parent_directory, 'reprojected_'+directory_name)
    # make reprojection directory if it does not yet exist
    if osp.exists(reprojection_directory):
        print(f'directory {reprojection_directory} already exists')
    else:
        os.makedirs(reprojection_directory)
        print(f'successfully created directory {reprojection_directory}')
    # reproject rasters
    print(f'\nreprojecting files in {directory} ...')
    for filename in tqdm(os.listdir(directory)):
        input_filepath = osp.join(directory, filename)
        output_filepath = osp.join(reprojection_directory, filename)
        reproject_raster(input_filepath, output_filepath, crs)
    print(f'\nsuccesfully projected all raster files in {directory} to {crs}\nreprojected files have been saved to {reprojection_directory}')
    return reprojection_directory

def tile_directory(directory: str, output_filepath=None):
    if not output_filepath:
        base_directory = osp.basename(directory)
        parent_directory = osp.dirname(directory)
        output_filepath = osp.join(parent_directory, 'tiled_'+base_directory)
    if osp.exists(output_filepath):
        print(f'file {output_filepath} already exists')
        return output_filepath
    
    filenames = os.listdir(directory)
    filepaths = [osp.join(directory, filename) for filename in filenames]
    print(f'tiling rasters in directory {directory} ...')
    gdal.Warp(
        destNameOrDestDS=output_filepath,
        srcDSOrSrcDSTab=filepaths,
        format='GTiff',
        resampleAlg='bilinear',
        creationOptions=[
            'COMPRESS=ZSTD', 'TILED=YES'
        ]
    )
    print(f'successfully saved tiled raster to file {output_filepath}')
    return output_filepath

def clip_raster(input_filepath, output_filepath=None, aoi_geojson_path=None):
    if not aoi_geojson_path:
        print('please provide a path to a geojson')
        return input_filepath
    if not output_filepath:
        input_filename = osp.basename(input_filepath)
        input_directory = osp.dirname(input_filepath)
        output_filepath = osp.join(input_directory, 'clipped_'+input_filename)
    if osp.exists(output_filepath):
        print(f'file {output_filepath} already exists')
        return output_filepath
    print(f'clipping raster in file {input_filepath}')
    input_raster = gdal.Open(input_filepath)
    band = input_raster.GetRasterBand(1)
    nodata_value = band.GetNoDataValue()
    if nodata_value is None:
        nodata_value=-20000
    del input_raster
    gdal.Warp(
        output_filepath,  # Output file
        input_filepath,   # Input raster file
        cutlineDSName=aoi_geojson_path,  # GeoJSON file for the boundary
        cropToCutline=True,  # Crop to the cutline
        dstNodata = nodata_value, 
        srcNodata = nodata_value, 
        creationOptions=[
            'COMPRESS=ZSTD', 'TILED=YES'
        ],
        options=[
            '-multi', '-wo', 'NUM_THREADS=ALL_CPUS'
        ]
    )
    print(f'successfully saved clipped raster to file {output_filepath}')
    return output_filepath

def plot_raster(filepath, cmap='magma'):
    if not osp.exists(filepath):
        print(f'file {filepath} does not exist')
        return
    raster = gdal.Open(filepath)
    band = raster.GetRasterBand(1)
    band_data = band.ReadAsArray()
    nodata_value = band.GetNoDataValue()
    if nodata_value is None:
        nodata_value = -20000 # this is the standard for USGS NBR
    del band
    del raster
    masked_band_data = np.ma.masked_equal(band_data, nodata_value)
    figure(figsize=(6,6))
    imshow(masked_band_data, cmap=cmap, interpolation='nearest')
    colorbar()
    show()