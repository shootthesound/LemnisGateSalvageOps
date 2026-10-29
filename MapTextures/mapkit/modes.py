"""Convert a map's objectives to another game mode.

Every mode has two gate pods (the teams' bases) plus its own objectives: flags for CTF, capture points for CAP,
turrets for DM, destroyable cores for DST, evac zones for EVA, a target for ASN. The game's *_Box maps show each
mode's working setup. A conversion removes the map's objectives, gives its pods the right class for the new mode
(CTF uses GatePodCTF), and places the new mode's objectives where its Box map has them relative to the pods: the same
distance along and across the line between the bases, scaled to this map. The editor then drops them onto the ground.
"""
import copy
import math

OBJECTIVES = {
    'CaptureTheFlags': ('FlagObjective_C',),
    'Capture': ('CapturableObjective_C',),
    'Deathmatch': ('CaptureTurret_C',),
    'Destroy': ('DestroyableObjective_C',),
    'Evacuate': ('EvacZone_C',),
    'Assassinate': ('AssassinateGameModePlaceable_C',),
}
BOX = {'CaptureTheFlags': 'CTF_Box', 'Capture': 'CAP_Box', 'Deathmatch': 'DM_Box', 'Destroy': 'DST_Box',
       'Evacuate': 'EVA_Box', 'Assassinate': 'ASN_Box'}
ALL_OBJECTIVES = {c for cs in OBJECTIVES.values() for c in cs}


def short(a):
    return a['class'].rsplit('.', 1)[1]


def is_pod(a):
    return short(a).startswith('GatePod')


def team(a):
    return 'Defender' if a['props'].get('TeamSide', (None, ''))[1] == 'ETeamSide::Defender' else 'Attacker'


def root_props(a):
    return a['components'][a['root']]['props']


def location(a):
    return list(root_props(a).get('RelativeLocation', ('Vector', [0, 0, 0]))[1])


def yaw(a):
    return root_props(a).get('RelativeRotation', ('Rotator', [0, 0, 0]))[1][1]


def frame(pods):
    """(attacker base, unit vector to the defender base, distance) from a map's two gate pods."""
    bases = {team(p): location(p) for p in pods}
    if set(bases) != {'Attacker', 'Defender'}:
        raise ValueError('the map needs an attacker and a defender gate pod')
    a, d = bases['Attacker'], bases['Defender']
    dx, dy = d[0] - a[0], d[1] - a[1]
    dist = math.hypot(dx, dy) or 1.0
    return a, (dx / dist, dy / dist), dist, (a[2] + d[2]) / 2


def convert(sc, box, mode):
    """Replace scene `sc`'s objectives with mode `mode`'s, laid out like scene `box` (that mode's Box map)."""
    pods = [a for a in sc['actors'] if is_pod(a)]
    box_pods = [a for a in box['actors'] if is_pod(a)]
    origin, axis, dist, ground = frame(pods)
    b_origin, b_axis, b_dist, b_ground = frame(box_pods)
    turn = math.degrees(math.atan2(axis[1], axis[0]) - math.atan2(b_axis[1], b_axis[0]))
    keep = [a for a in sc['actors'] if short(a) not in ALL_OBJECTIVES and not is_pod(a)]
    added = []
    # Gate pods: the mode's class and settings, at this map's bases.
    for bp in box_pods:
        src = next(p for p in pods if team(p) == team(bp))
        pod = copy.deepcopy(bp)
        pod['name'] = 'GatePod_%s' % team(bp)
        rp = root_props(pod)
        rp['RelativeLocation'] = ('Vector', location(src))
        rp['RelativeRotation'] = ('Rotator', list(root_props(src).get('RelativeRotation', ('Rotator', [0, 0, 0]))[1]))
        added.append(pod)
    # Objectives: same place relative to the bases.
    wanted = OBJECTIVES[mode]
    for k, bo in enumerate(a for a in box['actors'] if short(a) in wanted):
        p = location(bo)
        rx, ry = p[0] - b_origin[0], p[1] - b_origin[1]
        along = (rx * b_axis[0] + ry * b_axis[1]) / b_dist
        across = (-rx * b_axis[1] + ry * b_axis[0]) / b_dist
        x = origin[0] + (along * axis[0] - across * axis[1]) * dist
        y = origin[1] + (along * axis[1] + across * axis[0]) * dist
        z = ground + (p[2] - b_ground)
        obj = copy.deepcopy(bo)
        obj['name'] = '%s_%d' % (short(bo)[:-2], k + 1)
        rp = root_props(obj)
        rp['RelativeLocation'] = ('Vector', [x, y, z])
        rot = list(rp.get('RelativeRotation', ('Rotator', [0, 0, 0]))[1])
        rot[1] += turn
        rp['RelativeRotation'] = ('Rotator', rot)
        obj['snap'] = True
        added.append(obj)
    sc['actors'] = keep + added
    return len([a for a in added if a.get('snap')])
