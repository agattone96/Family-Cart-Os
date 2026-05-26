import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  View, Text, ScrollView, TouchableOpacity, TextInput, Modal,
  StyleSheet, ActivityIndicator, Alert, SafeAreaView, KeyboardAvoidingView, Platform, SectionList,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';
import { Colors, Shadows } from '../../src/utils/theme';
import { api, isInventoryDuplicateApiError } from '../../src/utils/api';
import { storage, storageKeys } from '../../src/utils/storage';
import type { InventoryBatchCreateConflict, InventoryItem, InventoryLocation } from '../../src/types/app';
import { useAppSession } from '../../src/context/AppSessionContext';

const LOCATIONS: InventoryLocation[] = ['pantry', 'fridge', 'freezer'];
const LOC_ICONS: Record<InventoryLocation, string> = {
  pantry: 'basket-outline',
  fridge: 'snow-outline',
  freezer: 'cube-outline',
};
const LOC_TITLES: Record<InventoryLocation, string> = {
  pantry: 'Pantry',
  fridge: 'Fridge',
  freezer: 'Freezer',
};

type StatusFilter = 'all' | 'low_stock' | 'expiring_soon';

interface ItemEditDraft {
  name: string;
  location: InventoryLocation;
  quantity: string;
  unit: string;
  category: string;
  expiry_date: string;
  low_stock_threshold: string;
  notes: string;
}

function emptyDraft(location: InventoryLocation): ItemEditDraft {
  return {
    name: '',
    location,
    quantity: '',
    unit: '',
    category: '',
    expiry_date: '',
    low_stock_threshold: '',
    notes: '',
  };
}

function draftFromItem(item: InventoryItem): ItemEditDraft {
  return {
    name: item.name || '',
    location: (item.location as InventoryLocation) || 'pantry',
    quantity: item.quantity != null ? String(item.quantity) : '',
    unit: item.unit || '',
    category: item.category || '',
    expiry_date: item.expiry_date || '',
    low_stock_threshold:
      item.low_stock_threshold != null ? String(item.low_stock_threshold) : '',
    notes: item.notes || '',
  };
}

function parseNumeric(value: string): number | null {
  if (!value || !value.trim()) return null;
  const n = parseFloat(value);
  return Number.isFinite(n) ? n : null;
}

export default function Inventory() {
  const { profile } = useAppSession();
  const initialLocation = ((profile?.last_inventory_location as InventoryLocation) ||
    'pantry') as InventoryLocation;
  const [allItems, setAllItems] = useState<InventoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState('');
  const [locationFilter, setLocationFilter] = useState<InventoryLocation | 'all'>('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');

  // Fast-add modal state.
  const [showAdd, setShowAdd] = useState(false);
  const [addDraft, setAddDraft] = useState<ItemEditDraft>(emptyDraft(initialLocation));
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [defaultLocation, setDefaultLocation] = useState<InventoryLocation>(initialLocation);

  // Edit modal state.
  const [editingItem, setEditingItem] = useState<InventoryItem | null>(null);
  const [editDraft, setEditDraft] = useState<ItemEditDraft | null>(null);

  // Photo extraction state.
  const [extracting, setExtracting] = useState(false);
  const [extracted, setExtracted] = useState<InventoryItem[]>([]);
  const [showExtracted, setShowExtracted] = useState(false);
  const [batchConflicts, setBatchConflicts] = useState<InventoryBatchCreateConflict[]>([]);
  const [batchSummaryMessage, setBatchSummaryMessage] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const stored = await storage.get(storageKeys.lastInventoryLocation);
      if (stored && (LOCATIONS as string[]).includes(stored)) {
        const loc = stored as InventoryLocation;
        setDefaultLocation(loc);
        setAddDraft((prev) => ({ ...prev, location: loc }));
      } else if (profile?.last_inventory_location) {
        const loc = profile.last_inventory_location as InventoryLocation;
        if ((LOCATIONS as string[]).includes(loc)) {
          setDefaultLocation(loc);
          setAddDraft((prev) => ({ ...prev, location: loc }));
        }
      }
    })();
  }, [profile?.last_inventory_location]);

  const load = useCallback(async () => {
    try {
      const data = await api.getInventory();
      setAllItems(Array.isArray(data) ? data : []);
    } catch (e) {
      console.error('Load inventory', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    load();
  }, [load]);

  const filteredItems = useMemo(() => {
    const term = searchText.trim().toLowerCase();
    return allItems.filter((item) => {
      if (item.archived_at) return false;
      if (locationFilter !== 'all' && item.location !== locationFilter) return false;
      if (statusFilter === 'low_stock' && !item.is_low_stock) return false;
      if (statusFilter === 'expiring_soon' && !item.is_expiring_soon) return false;
      if (term) {
        const haystack = `${item.name || ''} ${item.normalized_name || ''}`.toLowerCase();
        if (!haystack.includes(term)) return false;
      }
      return true;
    });
  }, [allItems, locationFilter, statusFilter, searchText]);

  const groupedSections = useMemo(() => {
    return LOCATIONS.map((loc) => ({
      title: LOC_TITLES[loc],
      location: loc,
      data: filteredItems.filter((item) => item.location === loc),
    })).filter((section) => section.data.length > 0);
  }, [filteredItems]);

  const lowStockCount = useMemo(
    () => allItems.filter((i) => !i.archived_at && i.is_low_stock).length,
    [allItems],
  );
  const expiringSoonCount = useMemo(
    () => allItems.filter((i) => !i.archived_at && i.is_expiring_soon).length,
    [allItems],
  );

  const openAddModal = (location?: InventoryLocation) => {
    const loc = location || defaultLocation;
    setAddDraft(emptyDraft(loc));
    setShowAdvanced(false);
    setShowAdd(true);
  };

  const handleAdd = async () => {
    const name = addDraft.name.trim();
    if (!name) {
      Alert.alert('Name required', 'Please enter an item name.');
      return;
    }
    const payload: Record<string, unknown> = { name, location: addDraft.location };
    const qty = parseNumeric(addDraft.quantity);
    if (qty !== null) payload.quantity = qty;
    if (addDraft.unit.trim()) payload.unit = addDraft.unit.trim();
    if (addDraft.category.trim()) payload.category = addDraft.category.trim();
    if (addDraft.expiry_date.trim()) payload.expiry_date = addDraft.expiry_date.trim();
    const threshold = parseNumeric(addDraft.low_stock_threshold);
    if (threshold !== null) payload.low_stock_threshold = threshold;
    if (addDraft.notes.trim()) payload.notes = addDraft.notes.trim();

    try {
      const item = await api.addInventoryItem(payload);
      setAllItems((prev) => [item, ...prev]);
      // Persist last-used location for fast repeat entry.
      setDefaultLocation(addDraft.location);
      storage.set(storageKeys.lastInventoryLocation, addDraft.location).catch(() => {});
      setShowAdd(false);
    } catch (e: any) {
      if (isInventoryDuplicateApiError(e)) {
        const duplicate = e.payload.duplicate;
        const existingItem = allItems.find((item) => item.id === duplicate.existing_item_id)
          || allItems.find(
            (item) => item.location === duplicate.location
              && item.normalized_name === duplicate.normalized_name,
          );
        const locationTitle = LOC_TITLES[duplicate.location];
        Alert.alert(
          'Duplicate item',
          `Already in ${locationTitle}.`,
          [
            ...(existingItem
              ? [{
                text: 'Edit existing item',
                onPress: () => {
                  setShowAdd(false);
                  openEditModal(existingItem);
                },
              }]
              : []),
            { text: 'Cancel', style: 'cancel' },
          ],
        );
        return;
      }
      Alert.alert('Error', e.message || 'Could not add item');
    }
  };

  const openEditModal = (item: InventoryItem) => {
    setEditingItem(item);
    setEditDraft(draftFromItem(item));
  };

  const handleEditSave = async () => {
    if (!editingItem || !editDraft) return;
    const name = editDraft.name.trim();
    if (!name) {
      Alert.alert('Name required', 'Please enter an item name.');
      return;
    }
    const payload: Record<string, unknown> = {
      name,
      location: editDraft.location,
      // Clearing an optional value: send null so the server unsets it.
      quantity: parseNumeric(editDraft.quantity),
      unit: editDraft.unit.trim() || null,
      category: editDraft.category.trim() || null,
      expiry_date: editDraft.expiry_date.trim() || null,
      low_stock_threshold: parseNumeric(editDraft.low_stock_threshold),
      notes: editDraft.notes.trim() || null,
    };
    try {
      const updated: InventoryItem = await api.updateInventoryItem(editingItem.id, payload);
      setAllItems((prev) => prev.map((it) => (it.id === editingItem.id ? updated : it)));
      setEditingItem(null);
      setEditDraft(null);
    } catch (e: any) {
      Alert.alert('Error', e.message || 'Could not update item');
    }
  };

  const handleArchive = async (item: InventoryItem) => {
    try {
      await api.archiveInventoryItem(item.id);
      setAllItems((prev) => prev.filter((it) => it.id !== item.id));
      setEditingItem(null);
      setEditDraft(null);
    } catch (e: any) {
      Alert.alert('Error', e.message || 'Could not archive item');
    }
  };

  const pickImage = async (useCamera: boolean) => {
    try {
      const perm = useCamera
        ? await ImagePicker.requestCameraPermissionsAsync()
        : await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        Alert.alert('Permission needed');
        return;
      }
      const result = useCamera
        ? await ImagePicker.launchCameraAsync({ base64: true, quality: 0.7 })
        : await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], base64: true, quality: 0.7 });
      if (result.canceled || !result.assets?.[0]?.base64) return;
      setExtracting(true);
      const res = await api.extractPhoto(result.assets[0].base64, defaultLocation);
      if (res.items?.length > 0) {
        setExtracted(res.items);
        setBatchConflicts([]);
        setBatchSummaryMessage(null);
        setShowExtracted(true);
      } else {
        Alert.alert('No items found', 'Try a clearer photo.');
      }
    } catch (e: any) {
      Alert.alert('Extraction Failed', e.message);
    } finally {
      setExtracting(false);
    }
  };

  const saveExtracted = async () => {
    try {
      const result = await api.addInventoryBatch(
        extracted.map((i) => ({
          name: i.name,
          quantity: i.quantity ?? undefined,
          unit: i.unit ?? undefined,
          location: defaultLocation,
        })),
      );
      const created = Array.isArray(result) ? result : result.created || [];
      const conflicts = Array.isArray(result) ? [] : result.conflicts || [];

      if (created.length > 0) {
        setAllItems((prev) => [...created, ...prev]);
      }
      if (conflicts.length > 0) {
        setBatchConflicts(conflicts);
        setBatchSummaryMessage(`Added ${created.length} items, ${conflicts.length} duplicates skipped.`);
      } else {
        setBatchConflicts([]);
        setBatchSummaryMessage(created.length > 0 ? `Added ${created.length} items.` : null);
      }
      setShowExtracted(false);
      setExtracted([]);
    } catch (e: any) {
      Alert.alert('Error', e.message);
    }
  };

  const renderItem = ({ item }: { item: InventoryItem }) => {
    const qtyDisplay =
      item.quantity != null
        ? `${item.quantity}${item.unit ? ` ${item.unit}` : ''}`
        : 'No quantity tracked';
    return (
      <TouchableOpacity
        style={[s.itemCard, item.is_low_stock && s.itemLowStock, item.is_expiring_soon && s.itemExpiring]}
        onPress={() => openEditModal(item)}
        activeOpacity={0.85}
        testID={`inventory-item-${item.id}`}
      >
        <View style={s.itemLeft}>
          <Text style={s.itemName}>{item.name}</Text>
          <Text style={s.itemQty}>{qtyDisplay}</Text>
          <View style={s.statusRow}>
            {item.is_low_stock && (
              <View style={[s.statusBadge, s.statusLow]} testID={`badge-low-${item.id}`}>
                <Ionicons name="alert-circle-outline" size={11} color={Colors.warning} />
                <Text style={s.statusLowText}>Low stock</Text>
              </View>
            )}
            {item.is_expiring_soon && (
              <View style={[s.statusBadge, s.statusExpire]} testID={`badge-expiring-${item.id}`}>
                <Ionicons name="time-outline" size={11} color={Colors.danger} />
                <Text style={s.statusExpireText}>Expiring soon</Text>
              </View>
            )}
            {item.category ? <Text style={s.itemCategory}>{item.category}</Text> : null}
          </View>
        </View>
        <Ionicons name="chevron-forward" size={18} color={Colors.textLight} />
      </TouchableOpacity>
    );
  };

  const renderSectionHeader = ({ section }: { section: { title: string; location: InventoryLocation } }) => (
    <View style={s.sectionHeader}>
      <Ionicons name={LOC_ICONS[section.location] as any} size={16} color={Colors.primary} />
      <Text style={s.sectionTitle}>{section.title}</Text>
      <TouchableOpacity
        style={s.sectionAdd}
        onPress={() => openAddModal(section.location)}
        testID={`section-add-${section.location}`}
      >
        <Ionicons name="add" size={16} color={Colors.primary} />
      </TouchableOpacity>
    </View>
  );

  const locationChips: { id: InventoryLocation | 'all'; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'pantry', label: 'Pantry' },
    { id: 'fridge', label: 'Fridge' },
    { id: 'freezer', label: 'Freezer' },
  ];

  return (
    <SafeAreaView style={s.safe}>
      <View style={s.header}>
        <Text style={s.title}>Inventory</Text>
        <Text style={s.subtitle}>Track what you have on hand</Text>
        {(lowStockCount > 0 || expiringSoonCount > 0) && (
          <View style={s.summaryStrip}>
            {lowStockCount > 0 && (
              <View style={[s.summaryChip, s.summaryChipLow]} testID="dashboard-low-stock">
                <Ionicons name="alert-circle-outline" size={12} color={Colors.warning} />
                <Text style={s.summaryChipLowText}>{lowStockCount} low stock</Text>
              </View>
            )}
            {expiringSoonCount > 0 && (
              <View style={[s.summaryChip, s.summaryChipExpire]} testID="dashboard-expiring">
                <Ionicons name="time-outline" size={12} color={Colors.danger} />
                <Text style={s.summaryChipExpireText}>{expiringSoonCount} expiring soon</Text>
              </View>
            )}
          </View>
        )}
      </View>

      {/* Search + Filters */}
      <View style={s.searchWrap}>
        <Ionicons name="search-outline" size={16} color={Colors.textLight} />
        <TextInput
          testID="inventory-search"
          style={s.searchInput}
          value={searchText}
          onChangeText={setSearchText}
          placeholder="Search items by name"
          placeholderTextColor={Colors.textLight}
        />
        {searchText.length > 0 && (
          <TouchableOpacity onPress={() => setSearchText('')} testID="clear-search">
            <Ionicons name="close-circle" size={16} color={Colors.textLight} />
          </TouchableOpacity>
        )}
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.filterRow}>
        {locationChips.map((chip) => {
          const active = locationFilter === chip.id;
          return (
            <TouchableOpacity
              key={chip.id}
              testID={`filter-loc-${chip.id}`}
              onPress={() => setLocationFilter(chip.id)}
              style={[s.filterChip, active && s.filterChipOn]}
            >
              <Text style={[s.filterChipText, active && s.filterChipTextOn]}>{chip.label}</Text>
            </TouchableOpacity>
          );
        })}
        <View style={s.filterDivider} />
        {(
          [
            { id: 'all', label: 'Any status' },
            { id: 'low_stock', label: 'Low stock' },
            { id: 'expiring_soon', label: 'Expiring soon' },
          ] as { id: StatusFilter; label: string }[]
        ).map((chip) => {
          const active = statusFilter === chip.id;
          return (
            <TouchableOpacity
              key={chip.id}
              testID={`filter-status-${chip.id}`}
              onPress={() => setStatusFilter(chip.id)}
              style={[s.filterChip, active && s.filterChipOn]}
            >
              <Text style={[s.filterChipText, active && s.filterChipTextOn]}>{chip.label}</Text>
            </TouchableOpacity>
          );
        })}
      </ScrollView>

      {/* Primary actions */}
      <View style={s.actions}>
        <TouchableOpacity
          testID="add-item-btn"
          style={[s.actionBtn, s.actionPrimary]}
          onPress={() => openAddModal()}
          activeOpacity={0.85}
        >
          <Ionicons name="add" size={16} color="#FFF" />
          <Text style={s.actionPrimaryText}>Fast add</Text>
        </TouchableOpacity>
        <TouchableOpacity testID="upload-photo-btn" style={s.actionBtn} onPress={() => pickImage(false)} disabled={extracting} activeOpacity={0.7}>
          <Ionicons name="image-outline" size={16} color={Colors.primary} />
          <Text style={s.actionText}>Photo</Text>
        </TouchableOpacity>
        <TouchableOpacity testID="camera-btn" style={s.actionBtn} onPress={() => pickImage(true)} disabled={extracting} activeOpacity={0.7}>
          <Ionicons name="camera-outline" size={16} color={Colors.primary} />
          <Text style={s.actionText}>Camera</Text>
        </TouchableOpacity>
      </View>

      {extracting && (
        <View style={s.banner}>
          <ActivityIndicator size="small" color={Colors.accent} />
          <Text style={s.bannerText}>Scanning photo...</Text>
        </View>
      )}
      {batchSummaryMessage && (
        <View style={[s.banner, s.duplicateBanner]} testID="batch-summary-banner">
          <Ionicons name="checkmark-done-outline" size={16} color={Colors.primary} />
          <Text style={s.bannerText}>{batchSummaryMessage}</Text>
        </View>
      )}
      {batchConflicts.length > 0 && (
        <View style={[s.banner, s.conflictsWrap]} testID="batch-conflicts-section">
          <Text style={s.duplicateTitle}>Review duplicates</Text>
          {batchConflicts.map((conflict) => (
            <Text key={`${conflict.index}-${conflict.existing_item_id}`} style={s.duplicateItem}>
              • {conflict.name} — {LOC_TITLES[conflict.location]}
            </Text>
          ))}
        </View>
      )}

      {loading ? (
        <View style={s.center}>
          <ActivityIndicator size="large" color={Colors.primary} />
        </View>
      ) : groupedSections.length === 0 ? (
        <View style={s.empty}>
          <View style={s.emptyIconWrap}>
            <Ionicons name="cube-outline" size={32} color={Colors.border} />
          </View>
          <Text style={s.emptyTitle}>
            {searchText || locationFilter !== 'all' || statusFilter !== 'all'
              ? 'No items match your filters'
              : 'Your inventory is empty'}
          </Text>
          <Text style={s.emptyBody}>
            Tap “Fast add” to track an item. Only name + location are required.
          </Text>
        </View>
      ) : (
        <SectionList
          sections={groupedSections}
          keyExtractor={(item) => item.id}
          renderItem={renderItem}
          renderSectionHeader={renderSectionHeader}
          stickySectionHeadersEnabled={false}
          contentContainerStyle={s.listContent}
          showsVerticalScrollIndicator={false}
        />
      )}

      {/* Fast Add Modal */}
      <Modal visible={showAdd} animationType="slide" transparent>
        <KeyboardAvoidingView style={s.modalOverlay} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
          <View style={s.modal}>
            <View style={s.modalHead}>
              <Text style={s.modalTitle}>Add inventory item</Text>
              <TouchableOpacity testID="close-add-modal" onPress={() => setShowAdd(false)}>
                <Ionicons name="close" size={22} color={Colors.textMuted} />
              </TouchableOpacity>
            </View>

            <Text style={s.fieldLabel}>Name *</Text>
            <TextInput
              testID="new-item-name"
              style={s.input}
              value={addDraft.name}
              onChangeText={(v) => setAddDraft({ ...addDraft, name: v })}
              placeholder="e.g. Greek yogurt"
              placeholderTextColor={Colors.textLight}
              autoFocus
              returnKeyType="done"
              onSubmitEditing={handleAdd}
            />

            <Text style={s.fieldLabel}>Location *</Text>
            <View style={s.locSegment}>
              {LOCATIONS.map((loc) => {
                const active = addDraft.location === loc;
                return (
                  <TouchableOpacity
                    key={loc}
                    testID={`new-item-location-${loc}`}
                    style={[s.locSeg, active && s.locSegOn]}
                    onPress={() => setAddDraft({ ...addDraft, location: loc })}
                  >
                    <Ionicons name={LOC_ICONS[loc] as any} size={14} color={active ? Colors.primary : Colors.textLight} />
                    <Text style={[s.locSegText, active && s.locSegTextOn]}>{LOC_TITLES[loc]}</Text>
                  </TouchableOpacity>
                );
              })}
            </View>

            <TouchableOpacity
              testID="toggle-advanced"
              style={s.advancedToggle}
              onPress={() => setShowAdvanced((v) => !v)}
              activeOpacity={0.7}
            >
              <Ionicons name={showAdvanced ? 'chevron-up' : 'chevron-down'} size={16} color={Colors.primary} />
              <Text style={s.advancedToggleText}>
                {showAdvanced ? 'Hide optional fields' : 'Add optional details'}
              </Text>
            </TouchableOpacity>

            {showAdvanced && (
              <View>
                <View style={s.inputRow}>
                  <View style={{ flex: 1, marginRight: 8 }}>
                    <Text style={s.fieldLabel}>Quantity</Text>
                    <TextInput
                      testID="new-item-qty"
                      style={s.input}
                      value={addDraft.quantity}
                      onChangeText={(v) => setAddDraft({ ...addDraft, quantity: v })}
                      placeholder="Optional"
                      keyboardType="numeric"
                      placeholderTextColor={Colors.textLight}
                    />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={s.fieldLabel}>Unit</Text>
                    <TextInput
                      testID="new-item-unit"
                      style={s.input}
                      value={addDraft.unit}
                      onChangeText={(v) => setAddDraft({ ...addDraft, unit: v })}
                      placeholder="lbs, cans..."
                      placeholderTextColor={Colors.textLight}
                    />
                  </View>
                </View>
                <Text style={s.fieldLabel}>Category</Text>
                <TextInput
                  testID="new-item-category"
                  style={s.input}
                  value={addDraft.category}
                  onChangeText={(v) => setAddDraft({ ...addDraft, category: v })}
                  placeholder="Produce, dairy, snacks..."
                  placeholderTextColor={Colors.textLight}
                />
                <Text style={s.fieldLabel}>Expiry date (YYYY-MM-DD)</Text>
                <TextInput
                  testID="new-item-expiry"
                  style={s.input}
                  value={addDraft.expiry_date}
                  onChangeText={(v) => setAddDraft({ ...addDraft, expiry_date: v })}
                  placeholder="Optional"
                  placeholderTextColor={Colors.textLight}
                />
                <Text style={s.fieldLabel}>Low-stock threshold</Text>
                <TextInput
                  testID="new-item-threshold"
                  style={s.input}
                  value={addDraft.low_stock_threshold}
                  onChangeText={(v) => setAddDraft({ ...addDraft, low_stock_threshold: v })}
                  placeholder="Alert when quantity is below this"
                  keyboardType="numeric"
                  placeholderTextColor={Colors.textLight}
                />
                <Text style={s.fieldLabel}>Notes</Text>
                <TextInput
                  testID="new-item-notes"
                  style={[s.input, { minHeight: 60 }]}
                  value={addDraft.notes}
                  onChangeText={(v) => setAddDraft({ ...addDraft, notes: v })}
                  placeholder="Optional details"
                  placeholderTextColor={Colors.textLight}
                  multiline
                />
              </View>
            )}

            <TouchableOpacity testID="save-item-btn" style={s.primaryBtn} onPress={handleAdd} activeOpacity={0.85}>
              <Text style={s.primaryBtnText}>Add to {LOC_TITLES[addDraft.location]}</Text>
            </TouchableOpacity>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Edit Modal */}
      <Modal visible={!!editingItem && !!editDraft} animationType="slide" transparent>
        <KeyboardAvoidingView style={s.modalOverlay} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
          <View style={s.modal}>
            <View style={s.modalHead}>
              <Text style={s.modalTitle}>Edit item</Text>
              <TouchableOpacity testID="close-edit-modal" onPress={() => { setEditingItem(null); setEditDraft(null); }}>
                <Ionicons name="close" size={22} color={Colors.textMuted} />
              </TouchableOpacity>
            </View>
            <ScrollView style={{ maxHeight: 480 }}>
              {editDraft && (
                <>
                  <Text style={s.fieldLabel}>Name *</Text>
                  <TextInput testID="edit-item-name" style={s.input} value={editDraft.name} onChangeText={(v) => setEditDraft({ ...editDraft, name: v })} />
                  <Text style={s.fieldLabel}>Location *</Text>
                  <View style={s.locSegment}>
                    {LOCATIONS.map((loc) => {
                      const active = editDraft.location === loc;
                      return (
                        <TouchableOpacity
                          key={loc}
                          testID={`edit-item-location-${loc}`}
                          style={[s.locSeg, active && s.locSegOn]}
                          onPress={() => setEditDraft({ ...editDraft, location: loc })}
                        >
                          <Ionicons name={LOC_ICONS[loc] as any} size={14} color={active ? Colors.primary : Colors.textLight} />
                          <Text style={[s.locSegText, active && s.locSegTextOn]}>{LOC_TITLES[loc]}</Text>
                        </TouchableOpacity>
                      );
                    })}
                  </View>
                  <View style={s.inputRow}>
                    <View style={{ flex: 1, marginRight: 8 }}>
                      <Text style={s.fieldLabel}>Quantity</Text>
                      <TextInput testID="edit-item-qty" style={s.input} value={editDraft.quantity} onChangeText={(v) => setEditDraft({ ...editDraft, quantity: v })} keyboardType="numeric" placeholder="Optional" placeholderTextColor={Colors.textLight} />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={s.fieldLabel}>Unit</Text>
                      <TextInput testID="edit-item-unit" style={s.input} value={editDraft.unit} onChangeText={(v) => setEditDraft({ ...editDraft, unit: v })} placeholder="lbs, cans..." placeholderTextColor={Colors.textLight} />
                    </View>
                  </View>
                  <Text style={s.fieldLabel}>Category</Text>
                  <TextInput testID="edit-item-category" style={s.input} value={editDraft.category} onChangeText={(v) => setEditDraft({ ...editDraft, category: v })} placeholder="Optional" placeholderTextColor={Colors.textLight} />
                  <Text style={s.fieldLabel}>Expiry date (YYYY-MM-DD)</Text>
                  <TextInput testID="edit-item-expiry" style={s.input} value={editDraft.expiry_date} onChangeText={(v) => setEditDraft({ ...editDraft, expiry_date: v })} placeholder="Optional" placeholderTextColor={Colors.textLight} />
                  <Text style={s.fieldLabel}>Low-stock threshold</Text>
                  <TextInput testID="edit-item-threshold" style={s.input} value={editDraft.low_stock_threshold} onChangeText={(v) => setEditDraft({ ...editDraft, low_stock_threshold: v })} keyboardType="numeric" placeholder="Optional" placeholderTextColor={Colors.textLight} />
                  <Text style={s.fieldLabel}>Notes</Text>
                  <TextInput testID="edit-item-notes" style={[s.input, { minHeight: 60 }]} value={editDraft.notes} onChangeText={(v) => setEditDraft({ ...editDraft, notes: v })} placeholder="Optional" placeholderTextColor={Colors.textLight} multiline />
                </>
              )}
            </ScrollView>
            <View style={s.editActions}>
              <TouchableOpacity
                testID="archive-item-btn"
                style={[s.secondaryBtn, s.archiveBtn]}
                onPress={() => editingItem && handleArchive(editingItem)}
                activeOpacity={0.85}
              >
                <Ionicons name="archive-outline" size={14} color={Colors.danger} />
                <Text style={s.archiveBtnText}>Archive</Text>
              </TouchableOpacity>
              <TouchableOpacity testID="save-edit-btn" style={[s.primaryBtn, { flex: 1, marginTop: 0 }]} onPress={handleEditSave} activeOpacity={0.85}>
                <Text style={s.primaryBtnText}>Save changes</Text>
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Extracted Photo Modal */}
      <Modal visible={showExtracted} animationType="slide" transparent>
        <View style={s.modalOverlay}>
          <View style={s.modal}>
            <View style={s.modalHead}>
              <Text style={s.modalTitle}>Found {extracted.length} Items</Text>
              <TouchableOpacity testID="close-extracted-modal" onPress={() => setShowExtracted(false)}>
                <Ionicons name="close" size={22} color={Colors.textMuted} />
              </TouchableOpacity>
            </View>
            <Text style={s.extractHint}>Review and edit before saving</Text>
            <ScrollView style={{ maxHeight: 280 }}>
              {extracted.map((item) => (
                <View key={item.id} style={s.extractRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={s.itemName}>{item.name}</Text>
                    <Text style={s.itemQty}>{item.quantity ?? ''} {item.unit ?? ''}</Text>
                  </View>
                  <TouchableOpacity
                    testID={`remove-extracted-${item.id}`}
                    onPress={() => setExtracted((p) => p.filter((i) => i.id !== item.id))}
                  >
                    <Ionicons name="close-circle" size={20} color={Colors.danger} />
                  </TouchableOpacity>
                </View>
              ))}
            </ScrollView>
            {extracted.length > 0 && (
              <TouchableOpacity testID="save-extracted-btn" style={s.primaryBtn} onPress={saveExtracted} activeOpacity={0.85}>
                <Text style={s.primaryBtnText}>Save {extracted.length} items</Text>
              </TouchableOpacity>
            )}
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: Colors.background },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  header: { paddingHorizontal: 20, paddingTop: 12 },
  title: { fontSize: 26, fontWeight: '700', color: Colors.textMain, letterSpacing: -0.4 },
  subtitle: { fontSize: 14, color: Colors.textMuted, marginTop: 2 },
  summaryStrip: { flexDirection: 'row', gap: 8, marginTop: 10, flexWrap: 'wrap' },
  summaryChip: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999, borderWidth: 1 },
  summaryChipLow: { borderColor: Colors.warning + '60', backgroundColor: Colors.warning + '14' },
  summaryChipLowText: { fontSize: 11, fontWeight: '700', color: Colors.warning },
  summaryChipExpire: { borderColor: Colors.danger + '40', backgroundColor: Colors.dangerMuted },
  summaryChipExpireText: { fontSize: 11, fontWeight: '700', color: Colors.danger },

  searchWrap: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: Colors.surface, borderRadius: 12, marginHorizontal: 20, marginTop: 14, paddingHorizontal: 12, paddingVertical: 8, borderWidth: 1, borderColor: Colors.border },
  searchInput: { flex: 1, fontSize: 14, color: Colors.textMain, paddingVertical: 4 },
  filterRow: { paddingHorizontal: 20, marginTop: 10, gap: 6, flexDirection: 'row', alignItems: 'center' },
  filterChip: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, backgroundColor: Colors.surface, borderWidth: 1, borderColor: Colors.border },
  filterChipOn: { backgroundColor: Colors.primary, borderColor: Colors.primary },
  filterChipText: { fontSize: 12, fontWeight: '600', color: Colors.textMuted },
  filterChipTextOn: { color: '#FFF' },
  filterDivider: { width: 1, height: 18, backgroundColor: Colors.border, marginHorizontal: 4 },

  actions: { flexDirection: 'row', paddingHorizontal: 20, marginTop: 12, gap: 8 },
  actionBtn: { flexDirection: 'row', alignItems: 'center', gap: 5, backgroundColor: Colors.surface, paddingHorizontal: 14, paddingVertical: 10, borderRadius: 10, borderWidth: 1, borderColor: Colors.border },
  actionPrimary: { backgroundColor: Colors.primary, borderColor: Colors.primary },
  actionPrimaryText: { fontSize: 13, fontWeight: '700', color: '#FFF' },
  actionText: { fontSize: 13, fontWeight: '600', color: Colors.primary },

  banner: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: Colors.surface, margin: 20, marginBottom: 0, padding: 12, borderRadius: 10, borderWidth: 1, borderColor: Colors.warning + '40' },
  bannerText: { fontSize: 13, color: Colors.textSecondary },
  duplicateBanner: { borderColor: Colors.primary + '35' },
  conflictsWrap: { alignItems: 'flex-start', flexDirection: 'column', gap: 4, borderColor: Colors.warning + '55' },
  duplicateTitle: { fontSize: 13, fontWeight: '700', color: Colors.textMain },
  duplicateItem: { fontSize: 13, color: Colors.textSecondary },

  listContent: { padding: 20, paddingBottom: 60 },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 18, marginBottom: 10 },
  sectionTitle: { fontSize: 13, fontWeight: '800', color: Colors.textMain, textTransform: 'uppercase', letterSpacing: 0.6, flex: 1 },
  sectionAdd: { padding: 4, borderRadius: 8, backgroundColor: Colors.primaryMuted },

  itemCard: { flexDirection: 'row', alignItems: 'center', backgroundColor: Colors.surface, borderRadius: 14, padding: 14, marginBottom: 8, borderWidth: 1, borderColor: Colors.border, ...Shadows.sm },
  itemLowStock: { borderColor: Colors.warning + '60', backgroundColor: Colors.warning + '0C' },
  itemExpiring: { borderColor: Colors.danger + '60', backgroundColor: Colors.dangerMuted },
  itemLeft: { flex: 1 },
  itemName: { fontSize: 15, fontWeight: '600', color: Colors.textMain },
  itemQty: { fontSize: 13, color: Colors.textMuted, marginTop: 2 },
  itemCategory: { fontSize: 11, color: Colors.textLight, textTransform: 'uppercase', letterSpacing: 0.5 },
  statusRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 6, flexWrap: 'wrap' },
  statusBadge: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, borderWidth: 1 },
  statusLow: { borderColor: Colors.warning + '60', backgroundColor: Colors.warning + '14' },
  statusLowText: { fontSize: 10, fontWeight: '700', color: Colors.warning },
  statusExpire: { borderColor: Colors.danger + '40', backgroundColor: Colors.dangerMuted },
  statusExpireText: { fontSize: 10, fontWeight: '700', color: Colors.danger },

  empty: { alignItems: 'center', marginTop: 60, paddingHorizontal: 40 },
  emptyIconWrap: { width: 64, height: 64, borderRadius: 32, backgroundColor: Colors.surfaceMuted, alignItems: 'center', justifyContent: 'center', marginBottom: 14 },
  emptyTitle: { fontSize: 16, fontWeight: '700', color: Colors.textMuted, textAlign: 'center' },
  emptyBody: { fontSize: 13, color: Colors.textLight, textAlign: 'center', marginTop: 6, lineHeight: 18 },

  modalOverlay: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.35)' },
  modal: { backgroundColor: Colors.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 24, paddingBottom: 36 },
  modalHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 },
  modalTitle: { fontSize: 18, fontWeight: '700', color: Colors.textMain },
  fieldLabel: { fontSize: 11, fontWeight: '700', color: Colors.textMuted, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6, marginTop: 6 },
  input: { backgroundColor: Colors.background, borderRadius: 10, padding: 14, fontSize: 15, color: Colors.textMain, borderWidth: 1, borderColor: Colors.border, marginBottom: 6 },
  inputRow: { flexDirection: 'row' },
  locSegment: { flexDirection: 'row', backgroundColor: Colors.surfaceMuted, borderRadius: 12, padding: 4, gap: 4, marginBottom: 10 },
  locSeg: { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 5, paddingVertical: 9, borderRadius: 9 },
  locSegOn: { backgroundColor: Colors.surface, ...Shadows.sm },
  locSegText: { fontSize: 12, fontWeight: '600', color: Colors.textLight },
  locSegTextOn: { color: Colors.primary, fontWeight: '700' },
  advancedToggle: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingVertical: 10 },
  advancedToggleText: { fontSize: 13, fontWeight: '700', color: Colors.primary },
  primaryBtn: { backgroundColor: Colors.primary, borderRadius: 12, paddingVertical: 15, alignItems: 'center', marginTop: 10 },
  primaryBtnText: { fontSize: 15, fontWeight: '700', color: '#FFF' },
  secondaryBtn: { borderRadius: 12, paddingVertical: 14, paddingHorizontal: 18, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 6 },
  archiveBtn: { backgroundColor: Colors.dangerMuted, borderWidth: 1, borderColor: Colors.danger + '40' },
  archiveBtnText: { fontSize: 13, fontWeight: '700', color: Colors.danger },
  editActions: { flexDirection: 'row', gap: 10, marginTop: 12, alignItems: 'center' },

  extractHint: { fontSize: 13, color: Colors.textMuted, marginBottom: 12 },
  extractRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: Colors.borderLight },
});
