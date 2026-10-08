"""Hand-designed (parametric) part moves and fixed routes: J1 escape + USB pair.

All mil, y-up. Produces DESIGN = {'moves': {...}, 'fixed': [ {cid, net, segs, vias} ]}.
"""
import math

S2 = math.sqrt(2)


def path(pts, layer, w):
    return [(tuple(a), tuple(b), layer, w) for a, b in zip(pts, pts[1:]) if math.dist(a, b) > 1e-6]


def build(P=None):
    P = dict(P or {})
    p = lambda k, d: P.get(k, d)
    moves = {}
    fixed = []

    def fx(cid, net, segs, vias=()):
        fixed.append({'cid': cid, 'net': net, 'segs': segs, 'vias': list(vias)})

    # ---------------------------------------------------------------- J1 pads (bottom)
    yA, yB = -1304.5, -1372.6
    X = {'A12': 482.3, 'A9': 541.3, 'A8': 561.0, 'A7': 580.7, 'A6': 600.4, 'A5': 620.1, 'A4': 639.8, 'A1': 698.8,
         'B1': 482.3, 'B4': 541.3, 'B5': 561.0, 'B6': 580.7, 'B7': 600.4, 'B8': 620.1, 'B9': 639.8, 'B12': 698.8}
    # VBUS between-row links
    fx('vbus-a9b4', 'VBUS_USB', path([(X['A9'], yA), (X['B4'], yB)], 2, 10))
    fx('vbus-a4b9', 'VBUS_USB', path([(X['A4'], yA), (X['B9'], yB)], 2, 10))
    # GND between-row links
    fx('gnd-a12b1', 'GND', path([(X['A12'], yA), (X['B1'], yB)], 2, 10))
    fx('gnd-a1b12', 'GND', path([(X['A1'], yA), (X['B12'], yB)], 2, 10))
    # DP link between rows (A6 -> B6) with one 45-degree jog
    yj = p('dp_link_y', -1328.7)
    fx('dp-link', 'USB_DP_CONN', path([(X['A6'], yA), (X['A6'], yj), (X['B6'], yj - 19.7), (X['B6'], yB)], 2, 10))
    # DM: B7 -> via below -> TOP -> via VJ on the (west-shifted) DM trunk
    yvb = p('vb7_y', -1410.0)
    xvj, yvj = p('vj_x', 566.0), p('vj_y', -1266.7)
    fx('dm-b7', 'USB_DM_CONN', path([(X['B7'], yB), (X['B7'], yvb)], 2, 10), [(X['B7'], yvb)])
    dx = X['B7'] - xvj
    yt = yvj - dx - p('dm_top_diag_gap', 0)            # start of diagonal on TOP
    fx('dm-top', 'USB_DM_CONN', path([(X['B7'], yvb), (X['B7'], yt), (xvj, yt + dx), (xvj, yvj)], 1, 10), [(xvj, yvj)])
    # DM trunk start: A7 north, NW jog to xvj ending exactly at VJ
    d7 = X['A7'] - xvj
    fx('dm-a7', 'USB_DM_CONN', path([(X['A7'], yA), (X['A7'], yvj - d7), (xvj, yvj)], 2, 10))

    # ---------------------------------------------------------------- CC
    # R4 (CC1 pulldown) moved right of A5, vertical, R4.1 south
    r4x, r4y1 = p('r4_x', 645.0), p('r4_y1', -1210.0)
    moves['R4'] = {'pad': '1', 'at': (r4x, r4y1), 'rot': 90}
    d = r4x - X['A5']
    fx('cc1', 'USB_CC1', path([(X['A5'], yA), (X['A5'], r4y1 - d), (r4x, r4y1)], 2, 8))
    # R5 (CC2 pulldown) directly below B5
    # R5 (CC2 pulldown) just below the lower-left shell leg, outside the connector body
    r5y1 = p('r5_y1', -1461.0)
    moves['R5'] = {'pad': '1', 'at': (450.0, r5y1), 'rot': 180}
    fx('cc2', 'USB_CC2', path([(X['B5'], yB), (X['B5'], r5y1 + 20.6), (X['B5'] - 20.6, r5y1), (450.0, r5y1)], 2, 8))

    # ---------------------------------------------------------------- VBUS: B9 straight down into F1.1
    f1y = p('f1_y', -1512.0)
    moves['F1'] = {'pad': '1', 'at': (X['B9'], f1y), 'rot': 180}   # F1.1 east at x=639.8
    fx('vbus-b9-neck', 'VBUS_USB', path([(X['B9'], yB), (X['B9'], -1398.0)], 2, 10))
    fx('vbus-b9-f1', 'VBUS_USB', path([(X['B9'], -1398.0), (X['B9'], f1y)], 2, 20))
    r8x = p('r8_x', 450.0)
    moves['R8'] = {'pad': '1', 'at': (r8x + 17.0, f1y), 'rot': 180}   # R8.1 east
    fx('n222', '$1N222', path([(X['B9'] - 113.8, f1y), (r8x + 17.0, f1y)], 2, 16))

    # ---------------------------------------------------------------- ESD diodes inline
    yd2 = p('d2_y', -1110.0)
    yd1 = p('d1_y', -1140.0)
    moves['D2'] = {'pad': '1', 'at': (xvj, yd2), 'rot': 180}      # D2.2 west
    moves['D1'] = {'pad': '1', 'at': (X['A6'], yd1), 'rot': 0}       # D1.2 east

    # ---------------------------------------------------------------- pair to the channel next to U1
    xdm, xdpc, xr6 = p('xdm', 650.0), p('xdpc', 676.0), p('xr6', 694.0)
    y0 = p('jog_y0', -1000.0)
    ddm, ddp = xdm - xvj, xdpc - X['A6']
    y2 = p('dp_jog2_y', -658.0)                 # DP second jog (above J2) start
    yr6_1 = y2 + (xr6 - xdpc) + p('r6_in', 10.0)
    moves['R6'] = {'pad': '1', 'at': (xr6, yr6_1), 'rot': 90}
    fx('dp-trunk', 'USB_DP_CONN', path([(X['A6'], yA), (X['A6'], y0), (xdpc, y0 + ddp), (xdpc, y2), (xr6, y2 + (xr6 - xdpc)), (xr6, yr6_1)], 2, 10))

    # ---------------------------------------------------------------- MCU side (R*.2 -> via -> TOP -> pin)
    pin26, pin27 = (630.0, -579.7), (630.0, -548.2)
    h6, k6 = p('v6_h', 31.03), p('v6_k', 15.0)
    v6 = (xr6 + k6, pin27[1] + h6)
    yr6_2 = yr6_1 + 34.0
    seg_b6 = [(xr6, yr6_2), (xr6, v6[1] - k6), v6] if k6 > 0 else [(xr6, yr6_2), v6]
    seg_t6 = [v6, (v6[0] - h6, pin27[1]), pin27] if h6 > 0 else [v6, pin27]
    fx('dp-mcu-b', 'USB_DP', path(seg_b6, 2, 10), [v6])
    fx('dp-mcu-t', 'USB_DP', path(seg_t6, 1, 10))
    usb_dp = sum(math.dist(a, b) for a, b in zip(seg_b6, seg_b6[1:])) + sum(math.dist(a, b) for a, b in zip(seg_t6, seg_t6[1:]))
    v7 = (p('v7_x', 664.0), p('v7_y', -579.7))
    k7 = v7[0] - xdm
    top7 = math.dist(v7, pin26)
    yr7_2 = v7[1] - k7 + k7 * S2 + top7 - usb_dp      # solve USB_DM == USB_DP
    yr7_1 = yr7_2 - 34.0
    moves['R7'] = {'pad': '1', 'at': (xdm, yr7_1), 'rot': 90}
    fx('dm-mcu-b', 'USB_DM', path([(xdm, yr7_2), (xdm, v7[1] - k7), v7], 2, 10), [v7])
    fx('dm-mcu-t', 'USB_DM', path([v7, pin26], 1, 10))
    fx('dm-trunk', 'USB_DM_CONN', path([(xvj, yvj), (xvj, y0), (xdm, y0 + ddm), (xdm, yr7_1)], 2, 10))

    # ================================================================ signal plan around U1
    # inward escapes (TOP stub into the module interior band, via to BOTTOM)
    yb, ybv = -646.7, -596.7          # bottom-row pin centre / inward via row
    xl, xlv = 165.4, 215.4            # left-column pin centre / inward via column
    V = {}
    for pin, net, x in (('U1.12', 'MIC_DATA', 208.7), ('U1.20', 'MIC_CLK', 460.7), ('U1.22', 'LED_GPIO8', 523.7), ('U1.23', 'BOOT_GPIO9', 555.2)):
        fx('esc-' + pin, net, path([(x, yb), (x, ybv)], 1, 8), [(x, ybv)])
        V[pin] = (x, ybv)
    for pin, net, y in (('U1.6', 'REC_KEY', -453.7), ('U1.8', 'CHIP_EN', -516.7)):
        fx('esc-' + pin, net, path([(xl, y), (xlv, y)], 1, 8), [(xlv, y)])
        V[pin] = (xlv, y)
    # pull-ups of GPIO8 / GPIO9 straight below their inward vias (BOTTOM)
    moves['R11'] = {'pad': '2', 'at': (523.7, -700.0), 'rot': 90}
    moves['R12'] = {'pad': '2', 'at': (555.2, -700.0), 'rot': 90}
    fx('pu-led', 'LED_GPIO8', path([V['U1.22'], (523.7, -700.0)], 2, 8))
    fx('pu-boot9', 'BOOT_GPIO9', path([V['U1.23'], (555.2, -700.0)], 2, 8))
    fx('pu-3v3', '3V3', path([(523.7, -734.0), (555.2, -734.0)], 2, 10))
    # BOOT2 / REC_KEY pull-ups on BOTTOM under the left cap strip (outside the module), via next to the pin
    for pin, net, y, des, padn, rot in (('U1.5', 'BOOT_GPIO2', -422.2, 'R10', '2', 0), ('U1.6', 'REC_KEY', -453.7, 'R18', '1', 180)):
        v = (115.0, y)
        moves[des] = {'pad': padn, 'at': (85.3, y), 'rot': rot}
        fx('pu-' + pin, net, path([(xl, y), v], 1, 8), [v])
        fx('pu-b-' + pin, net, path([v, (85.3, y)], 2, 8))
    # 3V3 rail under the cap strip: R18.2 - R10.1 - via VR; on TOP VR joins C3.1/C2.1 and pin 3
    vr = (51.2, -375.0)
    fx('pu-3v3-left', '3V3', path([(51.2, -453.7), (51.2, -422.2), vr], 2, 12), [vr])
    vr2 = (51.2, -640.0)
    fx('3v3-rail-s', '3V3', path([(51.2, -453.7), vr2], 2, 12), [vr2])
    fx('3v3-r9', '3V3', path([vr2, (51.2, -607.6)], 1, 12))
    fx('3v3-c3', '3V3', path([(51.2, -347.2), vr], 1, 12))
    fx('3v3-c2', '3V3', path([vr, (51.2, -400.8)], 1, 12))
    fx('3v3-pin3', '3V3', path([(165.4, -359.3), (51.2 + 15.7, -359.3), vr], 1, 12))
    # REC_KEY reaches J4.2 on TOP between J4 and J3/J2
    # bottom lane hugging the north edge of the module area, then TOP across to J4.2
    vrk = (720.0, -260.0)
    fx('reckey-bot', 'REC_KEY', path([(xlv, -453.7), (xlv, -290.0), (xlv + 30.0, -260.0), vrk], 2, 8), [vrk])
    fx('reckey-top', 'REC_KEY', path([vrk, (720.0, -481.0), (880.0, -641.0), (1045.2, -641.0), (1111.4, -574.8)], 1, 8))
    # microphone: MIC_DATA pull-down below its via, vias next to the mic pins (TOP pins)
    v45, v46, v44 = (895.0, -160.0), (936.4, -150.0), (936.4, -310.0)
    V['MIC_DATA'] = v45
    fx('mic-data-top', 'MIC_DATA', path([v45, (895.0, -216.2), (915.0, -236.2), (936.4, -236.2)], 1, 8), [v45])
    # MIC_DATA pull-down right below its inward via, just outside the module outline
    moves['R1'] = {'pad': '2', 'at': (208.7, -690.0), 'rot': 0}
    fx('mic-data-r1', 'MIC_DATA', path([(208.7, -596.7), (208.7, -690.0)], 2, 8))
    fx('mic-clk-top', 'MIC_CLK', path([v46, (936.4, -197.6)], 1, 8), [v46])
    fx('mic-3v3', '3V3', path([(988.0, -310.0), v44], 2, 10), [v44])
    fx('mic-3v3-top', '3V3', path([v44, (936.4, -274.8)], 1, 10))
    # amplifier inputs: vias under the U5 top-row pins, TOP bus from U1 lands on them
    V['U5.4'], V['U5.2'], V['U5.3'] = (1111.4, -838.0), (1011.4, -838.0), (1061.4, -838.0)
    for pin, net in (('U5.4', 'AMP_DIN'), ('U5.2', 'I2S_WS'), ('U5.3', 'I2S_BCLK')):
        x = V[pin][0]
        fx('u5-' + pin, net, path([V[pin], (x, -796.4)], 2, 8), [V[pin]])
    vac = (888.0, -950.0)
    V['AMP_CTRL'] = vac
    moves['R2'] = {'pad': '2', 'at': (888.0, -910.9), 'rot': 180}
    fx('amp-ctrl-b', 'AMP_CTRL', path([vac, (888.0, -910.9), (888.0, -869.8), (961.4, -796.4)], 2, 8), [vac])
    fx('r2-gnd', 'GND', path([(922.0, -910.9), (957.9, -910.9)], 2, 10))
    # SYS_ADC divider compact around R14.2
    moves['C19'] = {'pad': '2', 'at': (429.0, -775.6), 'rot': 0}
    moves['R15'] = {'pad': '1', 'at': (463.3, -810.0), 'rot': 270}
    fx('adc-c19', 'SYS_ADC', path([(429.0, -775.6), (463.3, -775.6)], 2, 8))
    fx('adc-r15', 'SYS_ADC', path([(463.3, -775.6), (463.3, -810.0)], 2, 8))
    return {'moves': moves, 'fixed': fixed, 'vias': V}


def lengths(design):
    L = {}
    for f in design['fixed']:
        for a, b, l, w in f['segs']:
            L[f['net']] = L.get(f['net'], 0) + math.dist(a, b)
    return L


if __name__ == '__main__':
    d = build()
    L = lengths(d)
    for k in sorted(L):
        print(f'{k:14s} {L[k]:8.1f}')
    print('CONN skew', L['USB_DP_CONN'] - L['USB_DM_CONN'], 'MCU skew', L['USB_DP'] - L['USB_DM'])
