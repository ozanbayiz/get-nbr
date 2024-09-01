from shapely.geometry import  mapping, Polygon, MultiPolygon, LineString, MultiLineString
from shapely.ops import unary_union, linemerge, polygonize

import pandas as pd
import geopandas as gpd

import os
import os.path as osp

# get scenes
bands = ['B5', 'B7']
scene_dataset = 'landsat_ot_c2_l2' 
band_dataset = 'landsat_band_files_c2_l2' # raw bands live in a different dataset

def get_geojson_boundary(path: str) -> dict:
    '''
    get boundary of a shapefile or geojson, returned as a single geojson feature
    ''' 
    gdf = gpd.read_file(path)
    gdf = gdf.to_crs(epsg=4326)
    combined_geometry = unary_union(gdf.geometry)
    if isinstance(combined_geometry, LineString):
        boundary_polygon = Polygon(combined_geometry)
    elif isinstance(combined_geometry, MultiLineString):
        merged = linemerge(boundary) 
        polygons = list(polygonize(merged))
        boundary_polygon = MultiPolygon(polygons)
    else:
        boundary = combined_geometry.boundary
        if isinstance(boundary, MultiLineString):
            merged = linemerge(boundary)
            polygons = list(polygonize(merged))
            boundary_polygon = MultiPolygon(polygons)
        elif isinstance(boundary, LineString):
            boundary_polygon = Polygon(boundary)
        else:
            # I'm really not sure why it would ever come to this cell, but just in case
            print(f'{path} is weird. it didnt work')
            return
    geojson = mapping(boundary_polygon)
    return geojson

def get_band_datasets(m2m, bands, params, get_earliest=True):
    params['datasetName'] = scene_dataset
    scenes = m2m.searchScenes(**params)
    print("Done\n{} - {} hits - {} returned".format(scene_dataset, scenes['totalHits'],scenes['recordsReturned']))

    # filter for most recent scenes in given date range
    print('\n    filtering for most recent scenes in date range ...', end=' ')
    scenes_df = pd.DataFrame(scenes['results'])[['entityId', 'publishDate']]
    scenes_df['pathRow'] = scenes_df['entityId'].str[3:9]
    grouped_scenes_df = (
        scenes_df
        .sort_values(by='publishDate', ascending=get_earliest)
        .groupby('pathRow')
        .agg(lambda sd: sd.iloc[0])
    )
    entityIds = list(grouped_scenes_df['entityId'])
    print(f'Done\n    {len(entityIds)} scenes remaining')

    # search for products
    print('\nsearching for products ...', end=' ')
    filterOptions = {
        'bulkAvailable': lambda x: x,
        'available': lambda x: x,
        'downloadSystem': lambda x: x=='folder',
        'secondaryDownloads': lambda x: x is not None
        
    }
    downloadOptions = m2m.downloadOptions(scene_dataset, filterOptions=filterOptions, entityIds=entityIds)
    print(f'Done\n{len(downloadOptions)} products found')
    print(f'\n    filtering duplicates ...', end=' ')
    downloadOptions_df = pd.DataFrame(downloadOptions)
    downloadOptions_df = downloadOptions_df.groupby('entityId').agg('first')
    print(f'Done\n    {len(downloadOptions_df)} products remaining')

    # select specific band files
    print(f'\nselecting band files ...')
    band_files = {}
    filtered_downloadOptions = downloadOptions_df.to_dict('records')
    for band in bands:
        band_downloads = []
        for product in filtered_downloadOptions:
            for secondaryDownload in product['secondaryDownloads']:
                if band in secondaryDownload['displayId']:
                    band_downloads.append(secondaryDownload)
        band_files[band] = band_downloads
        print(f'    {len(band_downloads)} band files found for {band}')
    return band_files

def download_band_datasets(m2m, band_files: dict)-> tuple:
    acq_directory = 'ingest'
    print('downloading band files ...')
    filterOptions = {
        'available': lambda x: x,
        'downloadName': lambda x: x is not None
    }
    bands = band_files.keys()
    band_filenames = {}
    band_metadata = {}
    for band in bands:
        print(f'    downloading {band} files ...')
        band_scenes = {'results': band_files[band]}
        band_metadata[band] = m2m.retrieveScenes(
            band_dataset,
            band_scenes, 
            filterOptions=filterOptions
        )
        band_filenames[band] = [file['displayId'] for file in band_files[band]]
    print(f'\nsuccesfully saved data to directory {acq_directory}')
    return band_filenames, band_metadata

def organize_band_files(acq_directory: str, data_directory: str, band_filenames: dict):
    # if `ingest` folder does not exist, cancel
    if not osp.exists(acq_directory):
        print(f'directory {acq_directory} does not exist')
        return
    if osp.exists(data_directory):
        print(f'directory "{data_directory}" already exists')
    else:
        os.makedirs(data_directory)
        print(f'successfully created directory {data_directory}')
    for band in band_filenames.keys():
        band_directory = osp.join(data_directory, band)
        if osp.exists(band_directory):
            print(f'\ndirectory "{band_directory}" already exists')
        else:
            os.makedirs(band_directory)
            print(f'\nsuccessfully created directory {band_directory}')
        for filename in band_filenames[band]:
            old_filepath = osp.join(acq_directory, filename)
            if osp.exists(old_filepath):
                new_filepath = osp.join(band_directory, filename)
                os.rename(old_filepath, new_filepath)
        print(f'successfully moved data to directory "{band_directory}"')
    # remove `acq_directory`
    for filename in os.listdir(acq_directory):
        os.remove(
            osp.join(acq_directory, filename)
        )
    os.rmdir(acq_directory)
    print(f'successfully removed {acq_directory}')