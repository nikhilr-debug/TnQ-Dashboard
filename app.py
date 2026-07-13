# ... existing code ...
            # --- EXPANDER 5: Misuse & Anomaly Flags (Last 30 Days) ---
            with st.expander("🚨 VL Misuse & Anomaly Flags (Last 30 Days)", expanded=False):
                # Calculate precise 30-day window metrics
                end_dt = pd.to_datetime(END_DATE)
                start_dt = end_dt - pd.Timedelta(days=30)
                
                df_30d = df_raw[(df_raw["company_name"].str.lower() == client) & 
                                (df_raw["_fod"] >= start_dt) & 
                                (df_raw["_fod"] <= end_dt)]
                
                desired_ms = MISUSE_SHOW_MS.get(client, [key_ms])
                show_ms = [m2 for m2 in desired_ms if m2 in ms_list]
                if key_ms not in show_ms:
                    show_ms = [key_ms] + show_ms
                show_ms = list(dict.fromkeys(show_ms))

                bm_30d = {}
                for m2 in show_ms:
                    col_has = f"has_{m2}"
                    if col_has in df_30d.columns and len(df_30d) > 0:
                        bm_30d[m2] = df_30d[col_has].mean() * 100
                    else:
                        bm_30d[m2] = 0
                bm_med_lt_30d = df_30d["candidate_lifetime_orders_trips"].astype(float).median() if len(df_30d) > 0 else 0

                misuse_rows = []
                for vln in filtered_vl_names:
                    grp = df_30d[df_30d["_vl"] == vln]
                    total_fods = len(grp)
                    if total_fods <= MIN_CURRENT_MTD_FODS: continue

                    zm = grp["ZM"].mode()[0] if not grp["ZM"].empty else "Unknown"
                    reg = grp["Region"].mode()[0] if not grp["Region"].empty else "Unknown"
                    cm = grp["CM"].mode()[0] if not grp["CM"].empty else "Unknown"
                    cl = grp["CL"].mode()[0] if not grp["CL"].empty else "Unknown"

                    lt_all = grp["candidate_lifetime_orders_trips"].astype(float)
                    med_lt = lt_all.median()
                    bel20 = (lt_all < 20).mean() * 100

                    reasons = []
                    sev_scores = []
                    critical_base_drops = []
                    standard_base_drops = []
                    is_critical_drop = False

                    for m2 in show_ms:
                        col_has = f"has_{m2}"
                        vl_pct = grp[col_has].mean() * 100 if col_has in grp.columns else 0
                        bv = bm_30d.get(m2, 0)
                        if bv > 0:
                            drop_pct = (bv - vl_pct) / bv
                            if drop_pct >= 0.50:  # Drop is >= 50%
                                is_critical_drop = True
                                critical_base_drops.append(f"F{m2}={vl_pct:.1f}% (≥50% drop from base {bv:.1f}%)")
                            elif drop_pct >= 0.15: # Standard drop
                                standard_base_drops.append(f"F{m2}={vl_pct:.1f}% (>{15}% drop from base {bv:.1f}%)")
                                sev_scores.append("high")

                    if med_lt < LT_CRITICAL:
                        reasons.append(f"Median LT = {med_lt:.1f} — ghost risk")
                        sev_scores.append("critical")
                    elif med_lt < LT_HIGH:
                        reasons.append(f"Median LT = {med_lt:.1f} — low")
                        sev_scores.append("high")

                    if bel20 > BELOW20_WATCH:
                        reasons.append(f"{bel20:.1f}% <20 LT")
                        sev_scores.append("watch")

                    if not reasons and not critical_base_drops and not standard_base_drops:
                        continue

                    if is_critical_drop:
                        sev_scores.append("critical")
                    elif not sev_scores and standard_base_drops:
                        sev_scores.append("watch")

                    final_sev = min(sev_scores, key=lambda s: {"critical": 0, "high": 1, "watch": 2}[s]) if sev_scores else "watch"
                    sev_label = {"critical": "❌ CRITICAL", "high": "🟠 HIGH", "watch": "🟡 WATCH"}[final_sev]

                    all_flags = []
                    if critical_base_drops:
                        all_flags.append("Critical Base Drops: " + ", ".join(critical_base_drops))
                    if standard_base_drops:
                        all_flags.append("Base Drops: " + ", ".join(standard_base_drops))
                    if reasons:
                        all_flags.extend(reasons)
                        
                    combined_reasons = " | ".join(all_flags)

                    row_data = {
                        "Client": client.title(),
                        "VL Name": vln,
                        "ZM": zm,
                        "Region": reg,
                        "CM": cm,
                        "CL": cl,
                        "Severity": sev_label,
                        "Total FODs": total_fods,
                        "Median LT": med_lt,
                    }

                    for m2 in show_ms:
                        col_has = f"has_{m2}"
                        vl_pct = grp[col_has].mean() * 100 if col_has in grp.columns else 0
                        bv = bm_30d.get(m2, 0)
                        dropped = (bv > 0) and (vl_pct < bv * 0.85)
                        row_data[f"F{m2}%"] = vl_pct
                        row_data[f"F{m2} Status"] = "⚠️ DROP" if dropped else "✓ OK"

                    row_data["Red Flags"] = combined_reasons
                    misuse_rows.append(row_data)

                if misuse_rows:
                    df_misuse = pd.DataFrame(misuse_rows)
                    severity_map = {"❌ CRITICAL": 0, "🟠 HIGH": 1, "🟡 WATCH": 2}
                    df_misuse["_sev_sort"] = df_misuse["Severity"].map(severity_map)
                    df_misuse = df_misuse.sort_values(by=["_sev_sort", "Total FODs"], ascending=[True, False]).drop(columns=["_sev_sort"])

                    bm_misuse = {
                        "Client": client.title(),
                        "VL Name": "⬛ BENCHMARK (Last 30 Days)",
                        "ZM": "", "Region": "", "CM": "", "CL": "", "Severity": "-",
                        "Total FODs": len(df_30d),
                        "Median LT": bm_med_lt_30d,
                        "Red Flags": "Overall Client Baseline (Last 30 Days)"
                    }
                    for m2 in show_ms:
                        bm_misuse[f"F{m2}%"] = bm_30d.get(m2, 0)
                        bm_misuse[f"F{m2} Status"] = ""

                    df_misuse = pd.concat([pd.DataFrame([bm_misuse]), df_misuse], ignore_index=True)

                    status_cols = [c for c in df_misuse.columns if str(c).endswith("Status")]
                    df_view = df_misuse.drop(columns=status_cols)
                    
                    # Ensure Client is the very first column
                    cols = df_view.columns.tolist()
                    cols.insert(0, cols.pop(cols.index('Client')))
                    df_view = df_view[cols]

                    st.dataframe(df_view.style.apply(highlight_severity_rows, axis=1)
                                                .map(highlight_misuse_status)
                                                .format(precision=2), 
                                 width="stretch", hide_index=True)
                else:
                    st.success("🎉 No vendor anomalies or quality warnings detected for the last 30 days!")

    # --- COMMERCIALS TAB ---
# ... existing code ...
