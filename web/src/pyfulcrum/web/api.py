#!/usr/bin/env python 
# -*- coding: utf-8 -*-

import logging
import math

from werkzeug.routing import BaseConverter, ValidationError
from flask import Blueprint, abort, current_app, Response, request, jsonify
from pyfulcrum.lib.api import ApiManager, PER_PAGE
from pyfulcrum.lib.formats import json_item, geojson_item, format_kml, format_csv, format_shapefile


class ResourcesConverter(BaseConverter):
    """
    Allows to validate resource types in url
    """
    resources = ApiManager.get_manager_names()

    def to_python(self, value):
        if value in self.resources:
            return value
        raise ValidationError()

    def to_url(self, value):
        return value

class FormatConverter(BaseConverter):
    """
    Allows to validate output format
    """
    formats = ('json', 'raw', 'geojson', 'csv', 'kml', 'shp', 'shapefile',)

    @classmethod
    def to_python(cls, value):
        if value in cls.formats:
            return value
        raise ValidationError()

    def to_url(self, value):
        return value


log = logging.getLogger(__name__)
api = Blueprint('pyfulcrum.web.api', __name__)

# hooking up resource type converter
def add_resources_converter(state):
    state.app.url_map.converters.update({'resource': ResourcesConverter,
                                         'format': FormatConverter})
api.record_once(add_resources_converter)


def spatial_only(resource_name, format):
    if resource_name not in  ('records', 'photos',):
        abort(Response("Resource type {} cannot be serialized to {} format"
                       .format(resource_name, format), status=400))


@api.route('/api/<resource:resource_name>/', methods=['GET'])
def list_resources(resource_name):
    config = current_app.config.get_namespace('API_')
    api_manager = ApiManager(**config)

    # format can be controlled with extension or format=X query param. query param
    # has precedense over extension.
    try:
        format = FormatConverter.to_python(request.args.get('format'))
    except ValidationError:
        format = 'json'
    is_spatial = resource_name in ('records', 'photos',) and format in ('kml', 'geojson', 'shp', 'shapefile',)
    with api_manager:
        res = api_manager.get_manager(resource_name)
        if not res:
            abort(Response("Resource not found: {}".format(resource_name), status=404))
        url_params = request.args.to_dict()
        page = int(url_params.get('page') or 0)
        per_page = int(url_params.get('per_page') or PER_PAGE)
        q = res.list(cached=True,
                     url_params=url_params,
                     is_spatial=is_spatial)
        count = q.count()
        total_pages = math.ceil(count/per_page)
        paged = q.offset(page * per_page).limit(per_page)

        if format == 'json':
            out = {'items': [json_item(r, api_manager.storage) for r in paged],
                   'total': count,
                   'per_page': per_page,
                   'total_pages': total_pages,
                   'page': page}

            return jsonify(out)

        elif format == 'raw':
            out = {resource_name: [r.payload for r in paged],
                   'total': count,
                   'per_page': per_page,
                   'total_pages': total_pages,
                   'page': page}

            return jsonify(out)
            

        elif format == 'geojson':
            spatial_only(resource_name, 'geojson')
            features = {'type': 'FeatureCollection',
                        'features': [geojson_item(r, api_manager.storage) for r in 
                                     paged],
                        'total': count,
                        'per_page': per_page,
                        'total_pages': total_pages,
                        'page': page}

            return jsonify(features)
        elif format == 'kml':
            spatial_only(resource_name, 'kml')
            kml_data = format_kml(paged, api_manager.storage, multiple=True)
            return Response(kml_data, mimetype='application/vnd.google-earth.kml+xml',
                            headers={'Content-Disposition': "attachment;filename={}.kml".format(resource_name)})
        elif format == 'csv':
            csv_data = format_csv(paged, api_manager.storage, multiple=True)
            return Response(csv_data, mimetype='text/csv',
                            headers={'Content-Disposition': "attachment;filename={}.csv".format(resource_name)})

        elif format in ('shp', 'shapefile'):
            spatial_only(resource_name, 'shapefile')
            shapefile = format_shapefile(paged, api_manager.storage, multiple=True)
            return Response(shapefile,
                            mimetype='application/zip',
                            headers={'Content-Disposition': "attachment;filename={}.zip".format(resource_name)})
        abort(400)
