"""Qualify private-VRAM self-BAR1 writes through each GPU's own IOMMU domain.

A complete hardware-negative result is valid evidence. Even four successful
self-loop words are controls, not cross-GPU P2P transfers or a P2P solution.
"""
import re


def fields(line):
    return dict(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)", line))


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def number(value, base=16):
    result = int(value, base)
    need(result >= 0, "Negative numeric field")
    return result


def u32(value):
    return value & 0xffffffff


def source_pattern(index, mode):
    return u32(0x35a761c9 ^ ((index + 1) * 0x1193a7d5) ^
               (mode * 0x6d2b79f1))


def target_sentinel(index, mode):
    return u32(0xc39e14a7 ^ ((index + 1) * 0x4b17d263) ^
               (mode * 0x92745b31))


def host_sentinel(index, mode, seq):
    return u32(0x8e51c3b9 ^ ((index + 1) * 0x71ad0965) ^
               (mode * 0x2d679f43) ^ (seq * 0x1337a921))


def cpu_pattern(index):
    return u32(0x4dd8a621 ^ ((index + 1) * 0x7c4f2935))


def cpu_sentinel(index):
    return u32(0x63b71dc9 ^ ((index + 1) * 0x29e4c583))


def alias_pattern_a(index):
    return u32(0x7ac351e9 ^ ((index + 1) * 0x16579b3d))


def alias_pattern_b(index):
    return u32(0x91de2f47 ^ ((index + 1) * 0x4cb78365))


def bit_count(value):
    return value.bit_count() if hasattr(int, "bit_count") else bin(value).count("1")


def check_mount_inventory(lines):
    mounts = [line.split() for line in lines
              if re.match(r"^\S+ /\S* \S+ \S+ \d+ \d+$", line)]
    types = {"/proc": "proc", "/sys": "sysfs", "/dev": "devtmpfs",
             "/run": "tmpfs", "/mnt/esp": "vfat"}
    need(mounts, "Mount inventory missing")
    for row in mounts:
        valid_root = row[1] == "/" and row[0] == "rootfs" and row[2] == "rootfs"
        valid_probe_mount = row[1] in types and row[2] == types.get(row[1])
        need(valid_root or valid_probe_mount, "Mount inventory contains unexpected filesystem")
    need(any(row[1] == "/mnt/esp" and row[2] == "vfat" for row in mounts),
         "Result ESP mount missing")


def check_dmar(kernel_lines):
    begins = [fields(line) for line in kernel_lines if "CASKDMAR_BEGIN " in line]
    caps = [fields(line) for line in kernel_lines if "CASKDMAR_CAP " in line]
    samples = [fields(line) for line in kernel_lines if "CASKDMAR_SAMPLE " in line]
    ends = [fields(line) for line in kernel_lines if "CASKDMAR_END " in line]
    unloads = [fields(line) for line in kernel_lines if "CASKDMAR_UNLOADED " in line]
    need(len(begins) == len(caps) == len(ends) == len(unloads) == 2,
         "DMAR lifecycle incomplete")
    need(all(item.get("units") == "1" and item.get("table_bytes") == "80" and
             item.get("register_writes") == "0" for item in begins),
         "DMAR table differs")
    need(all(item.get("base") == "fed91000" and item.get("ver") == "00000050" and
             item.get("cap") == "00d2008c40660462" and
             item.get("ecap") == "0000000000f050da" for item in caps),
         "DMAR identity differs")
    need(all(item.get("protocol_complete") == "1" and
             item.get("register_writes") == "0" for item in ends) and
         all(item.get("register_writes") == "0" for item in unloads),
         "DMAR completion absent")
    need(len(samples) == 4 and [item.get("index") for item in samples] ==
         ["0", "1", "0", "1"], "DMAR samples missing/reordered")
    for item in samples:
        gsts = number(item["gsts"])
        pmen = number(item["pmen"])
        need(gsts != 0xffffffff and ((gsts >> 31) & 1) == 1 and pmen == 0 and
             item.get("translation_enabled") == "1" and
             item.get("protected_region_enabled") == "0" and
             item.get("protected_region_status") == "0",
             "DMA translation not active or protected regions active")
        need(item.get("interrupt_remapping_enabled") ==
             str(int(bool(gsts & (1 << 25)))), "IRQ remap decode differs")


def one(rows, stage):
    matches = [row for row in rows if row.get("stage") == stage]
    need(len(matches) == 1, "Missing/duplicate " + stage)
    return matches[0]


def check_alias(row, index, owner):
    expected_a = alias_pattern_a(index)
    expected_b = alias_pattern_b(index)
    reset = target_sentinel(index, 0)
    need(row.get("owner") == owner and row.get("private_target") == "1" and
         row.get("rm_cpu_map") == "1" and row.get("alias_words") == "16",
         "Private BAR1 alias scope differs")
    need(all(row.get(name) == "0" for name in
             ["owner_a_mismatches", "cpu_a_mismatches", "owner_b_mismatches",
              "cpu_b_mismatches", "owner_reset_mismatches", "cpu_reset_mismatches"]),
         "Private BAR1 alias handshake mismatch")
    need(number(row["expected_a"]) == expected_a and number(row["cpu_a"]) == expected_a and
         number(row["expected_b"]) == expected_b and number(row["cpu_b"]) == expected_b and
         number(row["cpu_reset"]) == reset and number(row["alias_mask"]) == 0xf,
         "Private BAR1 alias handshake values differ")


def complete(raw, ccfg, kernel):
    lines = raw.splitlines()
    kernel_lines = kernel.splitlines()
    markers = [
        "IOVA_DMAR_BEFORE_BEGIN", "IOVA_DMAR_BEFORE_END",
        "IOVA_DMAR_AFTER_BEGIN", "IOVA_DMAR_AFTER_END",
        "IOVA_DATA_DISKS_UNMOUNTED", "NATIVE_TEST_RC=0", "SCRIPT_RC=0",
        "PROBE_COMPLETED",
    ]
    for marker in markers:
        need(lines.count(marker) == 1, "Missing/duplicate marker: " + marker)
    need("IOVA_WRITE_ERROR" not in raw and "IOVA_WRITE_PARKED" not in raw and
         "WATCHDOG_REBOOT" not in raw + kernel and "CASKIOVAWRITE" in kernel,
         "Aborted/error/watchdog or missing kernel evidence")
    need("intel_iommu=on iommu.passthrough=0 iommu.strict=1" in raw and
         "intel_iommu=off" not in raw and " iommu=off" not in raw,
         "Translated strict boot absent")
    need("IOVA_WRITE_PARAMETER=Y BUILTIN_TESTS_PARAMETER=1" in raw,
         "Diagnostic parameters absent")
    need(not re.search(r" /(?:mnt|media)/(?!esp(?: |/))", raw),
         "Unexpected mounted data path")
    check_mount_inventory(lines)

    for bdf, (_, expected_value) in ccfg.items():
        values = re.findall(r"^(?:PEG_CCFG|TCSS_CCFG) " + re.escape(bdf[5:]) +
                            r" ([0-9a-f]+)$", raw, re.M)
        need(len(values) == 3 and all(number(value) == expected_value for value in values),
             "Firmware CCFG differs")

    check_dmar(kernel_lines)
    need(not re.search(r"NVRM: Xid|DMAR:.*(?:fault|FAULT)|"
                       r"DMA Read NO_PASID|DMA Write NO_PASID|"
                       r"AER:|PCIe Bus Error:", kernel),
         "GPU/IOMMU/PCIe fault reported")
    need(not any("CASKIOVAWRITE" in line and "stage=retained" in line
                 for line in kernel_lines), "Uncertain DMA completion retained resources")

    begin_rows = [fields(line) for line in lines if line.startswith("IOVA_WRITE_BEGIN ")]
    need(len(begin_rows) == 2 and
         [row.get("execution_index") for row in begin_rows] == ["0", "1"],
         "Isolated client invocations missing/reordered")
    begin_controls = {
        "abi": "3", "private_rm_vidmem_target": "1",
        "dma_direction": "DMA_FROM_DEVICE", "self_bar1_loopback": "1",
        "cross_gpu_peer_transfer": "0", "ordinary_peer_access": "0",
        "host_staging_for_self": "0", "owner_gpu_readback_primary": "1",
        "cpu_write_control_after_self": "1", "cpu_control_is_p2p": "0",
        "isolated_process": "1",
    }
    need(all(all(row.get(key) == value for key, value in begin_controls.items())
             for row in begin_rows), "Client protocol scope differs")
    end_rows = [fields(line) for line in lines if line.startswith("IOVA_WRITE_END ")]
    need(len(end_rows) == 2 and
         [(row.get("execution_index"), row.get("protocol_complete"),
           row.get("p2p_solution_claimed")) for row in end_rows] ==
         [("0", "1", "0"), ("1", "1", "0")],
         "Isolated client completion missing/reordered")

    gpu_rows = [fields(line) for line in lines if line.startswith("IOVA_WRITE_GPU ")]
    need(len(gpu_rows) == 4 and [row.get("index") for row in gpu_rows] ==
         ["0", "1", "0", "1"],
         "Client GPU inventory missing/reordered")
    for position, row in enumerate(gpu_rows):
        index = position % 2
        expected_bdf = "0000:06:00.0" if index else "0000:01:00.0"
        need(row.get("bdf") == expected_bdf and row.get("peer_mapping") == "0" and
             int(row.get("local_registration_bytes", "0"), 10) > 0,
             "Client local-only registration differs")
    selected = [fields(line) for line in lines if line.startswith("IOVA_WRITE_FD_SELECTED ")]
    need(len(selected) == 2 and all(row.get("matches") == "1" and
         int(row.get("candidate_count", "0"), 10) >= 1 for row in selected),
         "UVM file selection not unique")

    ioctl_rows = [fields(line) for line in lines if line.startswith("IOVA_WRITE_IOCTL ")]
    need(len(ioctl_rows) == 2 and
         [(row.get("index"), row.get("request")) for row in ioctl_rows] ==
         [("0", "201"), ("1", "202")], "Client executions missing/reordered")

    native_rc = [fields(line) for line in lines if line.startswith("NATIVE_INDEX_RC ")]
    need([(row.get("index"), row.get("request"), row.get("rc")) for row in native_rc] ==
         [("0", "201", "0"), ("1", "202", "0")],
         "Per-index native return missing/reordered")
    gates = [fields(line) for line in lines if line.startswith("SELF_GATE ")]
    need(len(gates) == 1 and gates[0].get("index") == "0" and
         gates[0].get("observation_seconds") == "3" and
         gates[0].get("fault") == "0" and
         gates[0].get("proceed_to_index1") == "1",
         "Inter-GPU asynchronous-fault gate absent or failed")

    protocol_events = []
    for line in lines:
        if line.startswith("IOVA_WRITE_BEGIN "):
            protocol_events.append(("begin", fields(line).get("execution_index")))
        elif line.startswith("IOVA_WRITE_GPU "):
            protocol_events.append(("gpu", fields(line).get("index")))
        elif line.startswith("IOVA_WRITE_FD_SELECTED "):
            protocol_events.append(("fd", None))
        elif line.startswith("IOVA_WRITE_IOCTL "):
            protocol_events.append(("ioctl", fields(line).get("index")))
        elif line.startswith("IOVA_WRITE_END "):
            protocol_events.append(("end", fields(line).get("execution_index")))
        elif line.startswith("NATIVE_INDEX_RC "):
            protocol_events.append(("rc", fields(line).get("index")))
        elif line.startswith("SELF_GATE "):
            protocol_events.append(("gate", fields(line).get("index")))
    need(protocol_events == [("begin", "0"), ("gpu", "0"), ("gpu", "1"),
                             ("fd", None), ("ioctl", "0"), ("end", "0"),
                             ("rc", "0"), ("gate", "0"), ("begin", "1"),
                             ("gpu", "0"), ("gpu", "1"), ("fd", None),
                             ("ioctl", "1"), ("end", "1"), ("rc", "1")],
         "Client isolation/fault-gate sequence differs")

    rows = [fields(line) for line in kernel_lines if "CASKIOVAWRITE " in line]
    measured_rows = [row for row in rows if row.get("request") in ("201", "202")]
    need([(row.get("index"), row.get("request")) for row in measured_rows] ==
         [("0", "201")] * 12 + [("1", "202")] * 12,
         "Kernel executor blocks missing, extra, or reordered")
    gate_start = [line for line in kernel_lines
                  if "CASKLOGIC_SELF_GATE_START index=0" in line]
    gate_pass = [line for line in kernel_lines
                 if "CASKLOGIC_SELF_GATE_PASS index=0 fault=0 proceed=1" in line]
    need(len(gate_start) == len(gate_pass) == 1,
         "Kernel fault-gate markers missing/duplicated")
    need(not any("CASKLOGIC_SELF_GATE_FAIL" in line for line in kernel_lines),
         "Kernel fault gate reported failure")
    start_position = next(i for i, line in enumerate(kernel_lines)
                          if "CASKLOGIC_SELF_GATE_START index=0" in line)
    pass_position = next(i for i, line in enumerate(kernel_lines)
                         if "CASKLOGIC_SELF_GATE_PASS index=0 fault=0 proceed=1" in line)
    request_201_positions = [i for i, line in enumerate(kernel_lines)
                             if "CASKIOVAWRITE request=201 index=0 " in line]
    request_202_positions = [i for i, line in enumerate(kernel_lines)
                             if "CASKIOVAWRITE request=202 index=1 " in line]
    need(start_position < min(request_201_positions) and
         max(request_201_positions) < pass_position < min(request_202_positions),
         "Kernel fault gate does not separate the two GPU invocations")
    output = []
    self_alias_observations = []
    request_for_index = {0: 201, 1: 202}
    for index in (0, 1):
        request = request_for_index[index]
        subset = [row for row in rows if row.get("index") == str(index) and
                  row.get("request") == str(request)]
        expected_stage_order = (["host_mapping", "mapping", "alias"] +
                                ["result"] * 6 +
                                ["cpu_write_control", "mapping_stability", "return"])
        need([row.get("stage") for row in subset] == expected_stage_order,
             "Per-executor evidence missing, extra, or reordered")
        mapping = one(subset, "mapping")
        host = one(subset, "host_mapping")
        alias = one(subset, "alias")
        cpu_control = one(subset, "cpu_write_control")
        stability = one(subset, "mapping_stability")
        executor = "0000:06:00.0" if index else "0000:01:00.0"
        owner = executor

        need(mapping.get("executor") == executor and mapping.get("owner") == owner,
             "GPU placement differs")
        need(mapping.get("domain_type") == "3" and mapping.get("bar_index") == "1" and
             mapping.get("bytes") == "4096" and
             mapping.get("direction") == "DMA_FROM_DEVICE" and
             mapping.get("private_target") == "1" and mapping.get("rm_cpu_map") == "1" and
             mapping.get("ordinary_peer_mapping") == "0" and
             mapping.get("self_bar1") == "1" and
             mapping.get("owner_equals_executor") == "1" and
             mapping.get("cross_gpu_peer") == "0",
             "Private self-BAR1 DMA mapping scope differs")
        iova = number(mapping["iova"])
        physical = number(mapping["physical"])
        translated_first = number(mapping["translated_first"])
        translated_last = number(mapping["translated_last"])
        bar_start = number(mapping["bar_start"])
        bar_length = number(mapping["bar_length"])
        resource_flags = number(mapping["resource_flags"])
        page_level = int(mapping["cpu_pte_level"], 10)
        need(physical != 0 and iova != physical and not (iova & 4095) and
             not (physical & 4095) and translated_first == physical and
             translated_last == physical + 4095,
             "Private BAR1 IOVA endpoint translation differs")
        need(bar_start != 0 and bar_length >= 4096 and
             bar_start <= physical <= bar_start + bar_length - 4096 and
             (resource_flags & 0x2200) == 0x2200 and page_level == 1,
             "Private BAR1 resource/PTE qualification differs")

        host_iova = number(host["iova"])
        host_physical = number(host["physical"])
        need(host.get("executor") == executor and
             host.get("direction") == "DMA_BIDIRECTIONAL" and
             host.get("positive_control_only") == "1" and host.get("valid") == "1" and
             host_physical != 0 and number(host["translated"]) == host_physical,
             "Host positive-control mapping differs")
        check_alias(alias, index, owner)

        results = [row for row in subset if row.get("stage") == "result"]
        need(len(results) == 6 and [row.get("seq") for row in results] ==
             [str(seq) for seq in range(6)], "Six write operations missing/reordered")
        self_mask = 0
        for seq, result in enumerate(results):
            mode = 1 + seq // 3
            is_self = seq % 3 == 1
            expected = source_pattern(index, mode)
            sentinel = (target_sentinel(index, mode) if is_self else
                        host_sentinel(index, mode, seq))
            actual = number(result["actual"])
            alias_actual = number(result["alias_actual"])
            need(actual <= 0xffffffff and alias_actual <= 0xffffffff and
                 result.get("mode") == str(mode) and
                 result.get("kind") == ("self_bar1" if is_self else "host_ram") and
                 number(result["destination_iova"]) == (iova if is_self else host_iova) and
                 result.get("bytes") == "4",
                 "Write operation/address differs")
            need(number(result["expected"]) == expected and
                 number(result["sentinel"]) == sentinel and
                 result.get("match") == str(int(actual == expected)),
                 "Write data result inconsistent")
            need(result.get("guard_changed") == "0" and
                 result.get("source_changed") == "0" and
                 result.get("owner_gpu_readback") == str(int(is_self)) and
                 result.get("class") == "c7b5" and
                 number(result["launch"]) == 0x04003186 and
                 result.get("p2p_channel") == "0" and
                 result.get("privileged") == "1" and
                 result.get("host_relay") == "0" and
                 result.get("self_loopback") == str(int(is_self)) and
                 result.get("cross_gpu_peer") == "0",
                 "Primary readback, guard, source, or engine controls differ")
            need(result.get("alias_match") == str(int(is_self and alias_actual == expected)),
                 "Secondary alias observation inconsistent")
            if is_self:
                # The CPU BAR1 observation happens after the owner-GPU readback
                # and cannot redefine that primary result.
                self_alias_observations.append({
                    "index": index, "mode": mode, "actual": hex(alias_actual),
                    "matches_expected": alias_actual == expected,
                    "guard_changes": int(result["alias_guard_changed"], 10),
                })
                if actual == expected:
                    self_mask |= 1 << (mode - 1)
            else:
                need(actual == expected and alias_actual == 0 and
                     result.get("alias_match") == "0" and
                     result.get("alias_guard_changed") == "0",
                     "RAM positive control failed")

        control_pattern = cpu_pattern(index)
        control_sentinel = cpu_sentinel(index)
        cpu_actual = number(cpu_control["cpu_actual"])
        owner_actual = number(cpu_control["owner_actual"])
        reset_owner_mismatches = int(cpu_control["reset_owner_mismatches"], 10)
        reset_cpu_mismatches = int(cpu_control["reset_cpu_mismatches"], 10)
        cpu_reset = number(cpu_control["cpu_reset"])
        expected_cpu_mask = ((1 if owner_actual == control_pattern else 0) |
                             (2 if cpu_actual == control_pattern else 0) |
                             (4 if reset_owner_mismatches == 0 else 0) |
                             (8 if reset_cpu_mismatches == 0 else 0))
        need(cpu_actual <= 0xffffffff and owner_actual <= 0xffffffff and
             cpu_reset <= 0xffffffff and
             cpu_control.get("executor") == executor and
             cpu_control.get("owner") == owner and
             number(cpu_control["pattern"]) == control_pattern and
             number(cpu_control["sentinel"]) == control_sentinel,
             "CPU BAR1 control identity/data differs")
        need(cpu_control.get("cpu_match") == str(int(cpu_actual == control_pattern)) and
             cpu_control.get("owner_match") == str(int(owner_actual == control_pattern)) and
             cpu_control.get("guard_changed") == "0" and
             cpu_control.get("source_changed") == "0" and
             reset_owner_mismatches == 0 and
             number(cpu_control["cpu_control_mask"]) == expected_cpu_mask and
             expected_cpu_mask <= 0xf and
             (reset_cpu_mismatches != 0 or cpu_reset == control_sentinel),
             "CPU BAR1 primary result, reset, or safety controls differ")
        need(cpu_control.get("owner_gpu_readback_primary") == "1" and
             cpu_control.get("cpu_observation_secondary") == "1" and
             cpu_control.get("ordering") == "iowrite32_ioread32_flush" and
             cpu_control.get("after_self_results") == "1" and
             cpu_control.get("cross_gpu_peer") == "0" and
             cpu_control.get("control_only") == "1",
             "CPU BAR1 control scope/order differs")

        need(number(stability["physical"]) == physical and
             number(stability["iova_first_translation"]) == physical and
             number(stability["iova_last_translation"]) == physical + 4095 and
             stability.get("unchanged") == "1" and
             stability.get("target_mapping_live") == "1",
             "Private BAR1 mapping stability check failed")

        returns = [row for row in subset if row.get("stage") == "return" and
                   row.get("operation") == "1"]
        need(len(returns) == 1, "Execution return missing/duplicate")
        returned = returns[0]
        need(returned.get("status") == "0" and number(returned["flags"]) == 0xdf and
             number(returned["alias_mask"]) == 0xf and
             number(returned["host_mask"]) == 0x2d and
             number(returned["self_mask"]) == self_mask and
             number(returned["completed_mask"]) == 0x3f and
             number(returned["cpu_control_mask"]) == expected_cpu_mask and
             returned.get("pending") == "0" and returned.get("dma_unmapped") == "1" and
             returned.get("direction") == "DMA_FROM_DEVICE" and
             returned.get("last_phase") == "mapping_stability",
             "DMA mapping cleanup/lifecycle incomplete")

        client = [row for row in ioctl_rows if row.get("index") == str(index) and
                  row.get("request") == str(request)]
        need(len(client) == 1, "Client execution result absent")
        client = client[0]
        need(client.get("rv") == "0" and client.get("errno") == "0" and
             client.get("status") == "0" and number(client["flags"]) == 0xdf and
             client.get("domain") == "3" and number(client["alias_mask"]) == 0xf and
             number(client["host_mask"]) == 0x2d and
             number(client["self_mask"]) == self_mask and
             number(client["completed_mask"]) == 0x3f and
             number(client["cpu_control_mask"]) == expected_cpu_mask and
             number(client["bar1_phys"]) == physical and
             number(client["bar1_iova"]) == iova and
             number(client["bar1_start"]) == bar_start and
             int(client["pte_level"], 10) == page_level and
             client.get("inputs_unchanged") == "1",
             "Client/kernel results differ")

        output.append({
            "index": index, "request": request, "executor": executor, "owner": owner,
            "operations_completed": 6, "host_controls_passed": 4,
            "self_bar1_writes_attempted": 2,
            "self_bar1_writes_passed": bit_count(self_mask),
            "self_pass_mask": self_mask, "bar1_iova": hex(iova),
            "bar1_physical": hex(physical), "bar1_resource_start": hex(bar_start),
            "alias_handshake_words": 16, "alias_handshake_mask": 0xf,
            "owner_gpu_readback_primary": True, "mapping_stable": True,
            "dma_mapping_unmapped": True,
            "cpu_bar1_control": {
                "attempted": True,
                "passed_owner_gpu_primary": owner_actual == control_pattern,
                "cpu_observation_matched": cpu_actual == control_pattern,
                "reset_owner_gpu_verified": reset_owner_mismatches == 0,
                "reset_cpu_observation_matched": reset_cpu_mismatches == 0,
                "mask": expected_cpu_mask,
                "is_p2p": False,
            },
            "results": results,
        })

    need(len([row for row in rows if row.get("stage") == "result"]) == 12,
         "Unexpected extra GPU writes")
    need(len([row for row in rows if row.get("stage") == "cpu_write_control"]) == 2,
         "Unexpected CPU BAR1 control count")
    self_passed = sum(item["self_bar1_writes_passed"] for item in output)
    cpu_controls_passed = sum(int(item["cpu_bar1_control"]["passed_owner_gpu_primary"])
                              for item in output)
    scope = ("%d of four owner/self-GPU readbacks matched after translated private "
             "self-BAR1 word writes, bracketed by eight RAM controls. Self-loopback "
             "is a requester/route control, not a cross-GPU P2P transfer." % self_passed)
    return {
        "status": "complete_native_iova_private_vram_self_bar1",
        "protocol_complete": True,
        "executors": output,
        "translation_active_before_and_after": True,
        "mapping_stability_verified": True,
        "dma_direction": "DMA_FROM_DEVICE",
        "owner_gpu_readback_primary": True,
        "ordinary_peer_mappings": 0,
        "host_staging_for_self": False,
        "host_controls_passed": 8,
        "self_bar1_writes_attempted": 4,
        "self_bar1_writes_passed": self_passed,
        "self_alias_observations": self_alias_observations,
        "cross_gpu_peer_transfers": 0,
        "cpu_bar1_controls_attempted": 2,
        "cpu_bar1_controls_passed": cpu_controls_passed,
        "cpu_bar1_control_is_p2p": False,
        "cpu_bar1_control_after_self_results": True,
        "inter_gpu_async_fault_gate_passed": True,
        "cpu_bar1_control_scope": (
            "%d of two owner-GPU readbacks matched one-word CPU MMIO controls; "
            "these controls are not P2P transfers." % cpu_controls_passed
        ),
        "vm_data_disks_mounted": False,
        "P2P_solution_claimed": False,
        "general_P2P_proven": False,
        "scope": scope,
    }


def validate_log(raw, ccfg, kernel=""):
    try:
        return complete(raw, ccfg, kernel)
    except (ValueError, KeyError, TypeError, OverflowError) as error:
        return {"status": "incomplete_preserved", "protocol_complete": False,
                "error": str(error), "P2P_solution_claimed": False,
                "general_P2P_proven": False, "logs_are_partial_evidence": True}
