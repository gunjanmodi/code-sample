# system specific imports
import json
from operator import itemgetter
import time as t
from collections import deque
from threading import Thread
from collections import defaultdict
import traceback

# django specific imports
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils.safestring import mark_safe
from django.http import HttpResponse, StreamingHttpResponse
from django.contrib.sites.shortcuts import get_current_site
from django.conf import settings

# third party application imports
import requests

# project specific imports
from hierarchy.models import LineRelation
from LoadIQWeb.views import get_or_set_session_variables
from LoadIQWeb.models import Customer, Building, Device
from LoadIQWeb.utils import execute_query, convert_to_int, GLOBAL_COLOR_LIST, GLOBAL_COLOR_LIST_PRODUCER, \
    get_customer_name, create_vpn_route, logger_for_email_error
from users.models import UserBuildingAdmin


@login_required
def real_time(request):
    context = get_or_set_session_variables(request)

    current_site = get_current_site(request).domain
    real_time_building_api_host = "{0}:{1}".format(settings.REAL_TIME_BUILDING_API_HOST,
                                                   settings.REAL_TIME_BUILDING_API_PORT)
    context['current_site'] = mark_safe(current_site)
    context['real_time_building_api_host'] = mark_safe(real_time_building_api_host)

    customer_id = request.session["customer_id"]

    if "explore_customer" in request.session:
        if "building_in_view" in request.session:
            del request.session['building_in_view']
        context['explore_customer'] = request.session['explore_customer']
        # context['customer_name'] = Customer.objects.get(id=request.session["customer_id"]).name
        context['customer_name'] = get_customer_name(customer_id)
        context['customer_id'] = customer_id

    group_of_user = request.session.get('group_of_user', None)
    if "explore_customer" not in request.session and group_of_user in ("loadiq_superuser", "loadiq_channel_partner"):
        return redirect("/users/home")

    if group_of_user == 'loadiq_dashboard_user':
        return redirect('/dashboard/select_building')

    context['building_in_view'] = request.session.get("building_in_view", None)
    context['buildings'] = mark_safe(json.dumps(building_data_for_sidebar(customer_id, request.user)))

    context['page'] = 'realtime'
    context['customer_id'] = customer_id
    context['time_zone'] = request.session.get("time_zone")

    return render(request, 'real_time/real_time.html', context, content_type="text/html")


def real_time_building_data(request):
    building_id = request.GET.get('building_id', None)
    devices = Device.objects.filter(building_id=building_id).values('id')

    for device in devices:
        # Django server will always need a tunnel to the device
        create_vpn_route(device["id"])

    if building_id:
        # Define a generator to stream data directly to the client
        request.session["building_in_view"] = building_id
        response = StreamingHttpResponse(stream(building_id, request), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        response['Access-Control-Allow-Origin'] = '*'
        return response


def stream(building_id, request):
    devices = Device.objects.filter(building_id=building_id).values('id', 'name')
    virtual_line_data = virtual_line_info(building_id)
    circuit_and_line_data = circuit_and_line_data_for_real_time_building_api(building_id)

    real_power_data = dict()
    thread_data = dict()
    queue_data = dict()

    session_time = dict()
    sessions = requests.Session()
    for device in devices:
        key = "device_%s" % str(device["id"])
        thread_data[key] = dict()
        queue_data[key] = dict()
        queue_data[key]['queue'] = deque(maxlen=3)
        queue_data[key]['name'] = 'queue_%s' % (str(device["id"]))

        thread_data[key]['thread'] = Thread(target=process_real_time_data, args=(queue_data[key]['queue'],
                                                                                 device["id"],
                                                                                 circuit_and_line_data["circuit_data"],
                                                                                 session_time,
                                                                                 sessions))
        thread_data[key]['name'] = 'thread_%s' % (str(device["id"]))
        thread_data[key]['thread'].start()

    t.sleep(3)  # lets wait for 3 seconds to feed the queue and process the thread

    while True:
        session_time['time'] = t.time()
        time_key = int(t.time()) * 1000  # our custom time generation
        real_power_data[time_key] = dict({'time_stamp': time_key})
        real_power_data[time_key]['lines_real_power'] = {}

        for device in devices:
            key = "device_%s" % str(device["id"])
            
            try:
                queue_item = json.loads(queue_data[key]['queue'].popleft())
                for key, value in queue_item.iteritems():
                    """ if key == 'line_9191': # for testing purpose
                        print 'value send ', value """
                    real_power_data[time_key]['lines_real_power'][key] = value

            except IndexError:
                # In case of queue is empty popleft() throw IndexError
                # May be HOST API failed to return data for this[key] device
                logger_for_email_error(traceback.format_exc())

        level_counter = 1
        while level_counter <= virtual_line_data["max_level"]:
            for virtual_line_value in virtual_line_data["virtual_line_info"].itervalues():
                if virtual_line_value["level"] == level_counter:
                    siblings_real_power = parent_real_power = 0
                    try:
                        parent_key = "line_%s" % virtual_line_value["parent"]
                        parent_real_power = real_power_data[time_key]["lines_real_power"][parent_key]["real_power"]
                    except KeyError:
                        pass

                    for sibling in virtual_line_value["siblings"]:
                        sibling_key = "line_%s" % sibling
                        try:
                            siblings_real_power += real_power_data[time_key]["lines_real_power"][sibling_key][
                                "real_power"]
                        except KeyError:
                            pass

                    virtual_line_real_power = parent_real_power - siblings_real_power
                    if virtual_line_real_power:
                        virtual_line_key = "line_%s" % virtual_line_value["id"]
                        real_power_data[time_key]['lines_real_power'][virtual_line_key] = {
                            "real_power": virtual_line_real_power}

                else:
                    continue
            level_counter += 1

        if real_power_data[time_key]['lines_real_power']:
            yield "data: " + json.dumps(real_power_data[time_key]) + "\n\n"

        try:
            del real_power_data[time_key]
        except KeyError:
            pass

        t.sleep(1)


def process_real_time_data(q, device_id, circuit_information, session_time, s):
    real_power_data = dict()
    port_number = 60000 + device_id
    """
    Real time API data url
    """
    real_time_api_url = 'http://web.loadiq.com:%s/cgi-bin/real_time_data/real_time_data?circuit=all&plot_field=avg_real_power' % port_number

    try:
        r = s.get(real_time_api_url, stream=True)
    except Exception as e:
        create_vpn_route(device_id)
        return

    device_key = "device_%s" % device_id

    for chunk in r.iter_lines():
        if chunk:
            if 'data:' in chunk:
                chunk = chunk.split('data:')[-1]
                chunk = json.loads(chunk)

                circuit_data = chunk['cycle'][0]['circuit_data']
                time_stamp = 0
                try:
                    time_stamp = int(chunk['cycle'][0]['time_stamp'] / 1000)
                except KeyError as ke:
                    pass

                if time_stamp not in real_power_data:
                    # real_power_data[time_stamp] = dict({'time_stamp': time_stamp})
                    """
                    This is actual timestamp in device.
                    For now let's just ignore device timestamp. Use time by thread synchronization program. We
                    might reference in future if required.
                    """
                    real_power_data[time_stamp] = dict()

                # testing_value = 0
                for circuit_key, value in circuit_data.iteritems():
                    try:
                        
                        circuit_data = circuit_information[device_key][circuit_key]
                        line_key = 'line_%s' % circuit_data['line_id']
                        if line_key not in real_power_data[time_stamp]:
                            real_power_data[time_stamp][line_key] = dict({'real_power': 0})
                        real_power_data[time_stamp][line_key]['real_power'] += value['avg_real_power']
                    except KeyError:
                        pass
                
                """
                If connection is dead up to five seconds, close the threads
                """
                try:
                    if t.time() - session_time.get('time', t.time()) > 5:
                        s.close()
                        break

                    q.append(json.dumps(real_power_data[time_stamp]))  # append into queue in last
                    del real_power_data[time_stamp]
                except:
                    pass


def virtual_line_info(building_id):
    # cursor = get_cursor()
    max_level_query = """
        select
            ifnull(max(level),0)
        from
            hierarchy_line h
        where
            h.tree_id = (select
                    tree_id
                from
                    hierarchy_line
                where
                    hierarchy_line.object_id = {0})
                and h.node_type = 'VL'
    """.format(building_id)
    # cursor.execute(max_level_query)
    max_level_result_set = execute_query(max_level_query)

    virtual_lines_info_query = """
        select
            main_result_set.hierarchy_id,
            main_result_set.virtual_line_id,
            main_result_set.parent_id,
            main_result_set.parent_line_id,
            main_result_set.is_leaf,
            main_result_set.level,
            main_result_set.name,
            li.nick_name,
            li.description,
            (SELECT
                    GROUP_CONCAT(`hierarchy_line`.`object_id`)
                FROM
                    `hierarchy_line`
                WHERE
                    (`hierarchy_line`.`parent_id` = main_result_set.parent_id
                        AND NOT (`hierarchy_line`.`id` = main_result_set.hierarchy_id))
                ORDER BY `hierarchy_line`.`tree_id` ASC , `hierarchy_line`.`lft` ASC) as siblings
        from
            (select
                h.id as hierarchy_id,
                    h.object_id as virtual_line_id,
                    (select
                            id
                        from
                            hierarchy_line
                        where
                            id = h.parent_id) as parent_id,
                    (select
                            object_id
                        from
                            hierarchy_line
                        where
                            id = h.parent_id) as parent_line_id,
                    if(h.rght = h.lft + 1, 1, 0) is_leaf,
                    h.level,
                    v.name
            from
                hierarchy_line h
            inner join virtual_line v ON h.object_id = v.id
            where
                h.tree_id = (select
                        tree_id
                    from
                        hierarchy_line
                    where
                        hierarchy_line.object_id = {0})
                    and h.node_type = 'VL') as main_result_set
                        LEFT JOIN
                    line_info li ON li.line_id = main_result_set.parent_line_id
    """.format(str(building_id))

    virtual_line_result_set = execute_query(virtual_lines_info_query)

    virtual_lines_info = {}
    for hierarchy_id, virtual_line_id, parent_id, parent_line_id, is_leaf, level, name, nick_name, description, siblings \
            in virtual_line_result_set:
        line_id = str(virtual_line_id)
        virtual_lines_info[line_id] = {"id": int(virtual_line_id),
                                       "name": str(name),
                                       "parent": int(parent_line_id),
                                       "siblings": map(convert_to_int, siblings.split(',')),
                                       'nick_name': 'Other-{0}'.format(nick_name) if nick_name else None,
                                       'description': description,
                                       "level": int(level),
                                       "is_leaf": bool(is_leaf)
                                       }
    return {'virtual_line_info': virtual_lines_info, 'max_level': int(max_level_result_set[0][0])}


def circuit_and_line_data_for_real_time_building_api(building_id):
    query = """
        select
            (line_data.circuit_id - count_data.min_circuit_id) as circuit_count,
            line_data . *
        from
            (select
                circuit.id as circuit_id,
                    circuit.name as phase,
                    line.id as line_id,
                     COALESCE(li.nick_name, line.name) AS `line_name`,
                    ifnull(line.code, 'consumer') as line_code,
                    device.id as device_id,
                    if(h.rght = h.lft + 1,1,0) is_leaf,
                    li.nick_name AS `nick_name`,
                    line.name,
                    li.description
            from
                circuit
            inner join line ON circuit.line_id = line.id
            inner JOIN device ON line.device_id = device.id
            inner JOIN building ON device.building_id = building.id
            inner JOIN customer ON building.customer_id = customer.id
            inner join hierarchy_line h on h.object_id = line.id
            left join line_info li on li.line_id = line.id
            where
                building.id = {0}
                    and circuit.phase_no > 0
                    and building.name <> ' '
                    and line.name not in (' ' , 'unassigned')
            order by circuit_id, line_id) as line_data
                inner join
            (select
                device.id as device_id, min(circuit.id) as min_circuit_id
            from
                circuit
            inner join line ON line.id = circuit.line_id
            inner join device ON device.id = line.device_id
            inner join building ON building.id = device.building_id
            where
                building.id = {0}
                    and circuit.phase_no > 0
            group by device.id) as count_data ON line_data.device_id = count_data.device_id
    """.format(building_id)

    result_set = execute_query(query)

    circuit_data = dict()

    line_data = defaultdict(str)
    for circuit_count, circuit_id, phase, line_id, line_name, line_code, device_id, is_leaf, nick_name, real_name, description in result_set:
        circuit_key = "circuit_%s" % circuit_count
        device_key = "device_%s" % device_id
        line_key = "line_%s" % line_id

        line_data[line_key] = {
            "line_id": line_id,
            "line_name": line_name,
            "line_code": line_code,
            "is_leaf": bool(is_leaf),
            'nick_name': nick_name,
            'real_name': real_name,
            'description': description
        }

        if device_key not in circuit_data:
            circuit_data[device_key] = dict()
        circuit_data[device_key][circuit_key] = {
            'circuit_id': circuit_id,
            'phase': phase,
            'line_id': line_id,
            'line_name': line_name,
            'real_name': real_name,
            'description': description,
            'line_code': line_code,
            'device_id': device_id
        }

    return {"line_data": line_data, "circuit_data": circuit_data}
