import React, { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { Colors, Shadows } from '../utils/theme';
import { api } from '../utils/api';
import type { InventoryDashboard, InventoryItem } from '../types/app';

interface Props {
  /** Optional pre-fetched snapshot. When supplied no network call is made. */
  initialData?: InventoryDashboard | null;
  /** Used by tests to inject a deterministic fetcher. */
  fetcher?: () => Promise<InventoryDashboard>;
  testID?: string;
}

function ItemRow({ item, kind }: { item: InventoryItem; kind: 'low' | 'expire' }) {
  return (
    <View style={s.itemRow}>
      <Ionicons
        name={kind === 'low' ? 'alert-circle-outline' : 'time-outline'}
        size={14}
        color={kind === 'low' ? Colors.warning : Colors.danger}
      />
      <Text style={s.itemRowName} numberOfLines={1}>
        {item.name}
      </Text>
      {item.expiry_date && kind === 'expire' && (
        <Text style={s.itemRowMeta}>{item.expiry_date}</Text>
      )}
      {item.quantity != null && kind === 'low' && (
        <Text style={s.itemRowMeta}>
          {item.quantity}
          {item.unit ? ` ${item.unit}` : ''}
        </Text>
      )}
    </View>
  );
}

export default function InventorySnapshotCard({ initialData, fetcher, testID }: Props) {
  const router = useRouter();
  const [data, setData] = useState<InventoryDashboard | null>(initialData ?? null);
  const [loading, setLoading] = useState(!initialData);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (initialData) return;
    let cancelled = false;
    (async () => {
      try {
        const loader = fetcher || (() => api.getInventoryDashboard());
        const res = (await loader()) as InventoryDashboard;
        if (!cancelled) setData(res);
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'Could not load inventory snapshot');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [fetcher, initialData]);

  return (
    <View style={s.card} testID={testID || 'inventory-snapshot'}>
      <View style={s.headerRow}>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Inventory snapshot</Text>
          <Text style={s.subtitle}>What is running low or expiring soon.</Text>
        </View>
        <TouchableOpacity
          style={s.openBtn}
          onPress={() => router.push('/(tabs)/inventory')}
          testID="open-inventory-btn"
        >
          <Text style={s.openBtnText}>Open</Text>
          <Ionicons name="chevron-forward" size={14} color={Colors.primary} />
        </TouchableOpacity>
      </View>

      {loading ? (
        <View style={s.loading}>
          <ActivityIndicator size="small" color={Colors.primary} />
        </View>
      ) : error ? (
        <Text style={s.error}>{error}</Text>
      ) : data ? (
        <View>
          <View style={s.statsRow}>
            <View style={[s.statBox, s.statLow]} testID="snapshot-low-count">
              <Text style={s.statValue}>{data.low_stock_count}</Text>
              <Text style={s.statLabel}>Low stock</Text>
            </View>
            <View style={[s.statBox, s.statExpire]} testID="snapshot-expiring-count">
              <Text style={s.statValue}>{data.expiring_soon_count}</Text>
              <Text style={s.statLabel}>Expiring soon</Text>
            </View>
            <View style={s.statBox} testID="snapshot-total">
              <Text style={s.statValue}>{data.active_total}</Text>
              <Text style={s.statLabel}>Active items</Text>
            </View>
          </View>

          {data.low_stock_count === 0 && data.expiring_soon_count === 0 ? (
            <Text style={s.allGood}>Everything looks good in the fridge, freezer, and pantry.</Text>
          ) : (
            <View>
              {data.low_stock.slice(0, 3).map((item) => (
                <ItemRow key={`low-${item.id}`} item={item} kind="low" />
              ))}
              {data.expiring_soon.slice(0, 3).map((item) => (
                <ItemRow key={`exp-${item.id}`} item={item} kind="expire" />
              ))}
              <Text style={s.windowLabel}>
                Using a {data.expiring_soon_days}-day expiring window.
              </Text>
            </View>
          )}
        </View>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  card: {
    backgroundColor: Colors.surface,
    borderRadius: 22,
    padding: 20,
    borderWidth: 1,
    borderColor: Colors.border,
    ...Shadows.sm,
    gap: 12,
  },
  headerRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  title: { fontSize: 16, fontWeight: '800', color: Colors.textMain },
  subtitle: { fontSize: 13, color: Colors.textMuted, marginTop: 3 },
  openBtn: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: Colors.primary + '30' },
  openBtnText: { fontSize: 12, fontWeight: '700', color: Colors.primary },
  loading: { alignItems: 'center', paddingVertical: 18 },
  error: { color: Colors.danger, fontSize: 13 },
  statsRow: { flexDirection: 'row', gap: 8 },
  statBox: { flex: 1, padding: 12, borderRadius: 12, backgroundColor: Colors.surfaceMuted },
  statLow: { backgroundColor: Colors.warning + '12' },
  statExpire: { backgroundColor: Colors.dangerMuted },
  statValue: { fontSize: 20, fontWeight: '800', color: Colors.textMain },
  statLabel: { fontSize: 11, color: Colors.textMuted, marginTop: 2, fontWeight: '600' },
  itemRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 6, borderTopWidth: 1, borderTopColor: Colors.borderLight },
  itemRowName: { flex: 1, fontSize: 13, fontWeight: '600', color: Colors.textSecondary },
  itemRowMeta: { fontSize: 11, color: Colors.textLight, fontWeight: '600' },
  allGood: { fontSize: 13, color: Colors.textMuted, lineHeight: 19 },
  windowLabel: { fontSize: 11, color: Colors.textLight, marginTop: 8, fontStyle: 'italic' },
});
