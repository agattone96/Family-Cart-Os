import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import ChipSelector from '../../src/components/ChipSelector';
import InventorySnapshotCard from '../../src/components/InventorySnapshotCard';
import NumberStepper from '../../src/components/NumberStepper';
import { useAppSession } from '../../src/context/AppSessionContext';
import {
  DEFAULT_COOKING_STYLES,
  DEFAULT_DIETARY_RULES,
  DEFAULT_MEAL_COVERAGE,
  DEFAULT_STORES,
  PRICE_MODES,
  TRIP_TYPES,
} from '../../src/data/options';
import { useResponsive } from '../../src/hooks/useResponsive';
import { api } from '../../src/utils/api';
import { Colors, Shadows } from '../../src/utils/theme';

function SectionCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <View style={s.card}>
      <Text style={s.cardTitle}>{title}</Text>
      {subtitle ? <Text style={s.cardSubtitle}>{subtitle}</Text> : null}
      {children}
    </View>
  );
}

function Label({ children }: { children: string }) {
  return <Text style={s.label}>{children}</Text>;
}

export default function ThisWeek() {
  const router = useRouter();
  const { profile, refreshProfile } = useAppSession();
  const { contentMaxWidth, columns, gutter, isDesktop } = useResponsive();
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [tripType, setTripType] = useState('Full week');
  const [budget, setBudget] = useState('200');
  const [adults, setAdults] = useState(4);
  const [children, setChildren] = useState(0);
  const [stores, setStores] = useState<string[]>([]);
  const [meals, setMeals] = useState<string[]>([]);
  const [cookingStyle, setCookingStyle] = useState<string[]>([]);
  const [dietaryRules, setDietaryRules] = useState<string[]>([]);
  const [exclusions, setExclusions] = useState('');
  const [priceMode, setPriceMode] = useState('No prices');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [promptOverride, setPromptOverride] = useState('');
  const [customInstructions, setCustomInstructions] = useState('');
  const [householdContextOverride, setHouseholdContextOverride] = useState('');
  const [inventoryContextOverride, setInventoryContextOverride] = useState('');
  const [requiredItemsContextOverride, setRequiredItemsContextOverride] = useState('');
  const [planningNotes, setPlanningNotes] = useState('');
  const [customStoreInput, setCustomStoreInput] = useState('');
  const [customCookingInput, setCustomCookingInput] = useState('');
  const [customMealInput, setCustomMealInput] = useState('');
  const [customDietaryInput, setCustomDietaryInput] = useState('');
  const [customExclusionInput, setCustomExclusionInput] = useState('');
  const [saveNewDefaults, setSaveNewDefaults] = useState(true);
  const [customStoreOptions, setCustomStoreOptions] = useState<string[]>([]);
  const [customCookingOptions, setCustomCookingOptions] = useState<string[]>([]);
  const [customMealOptions, setCustomMealOptions] = useState<string[]>([]);
  const [customDietaryTags, setCustomDietaryTags] = useState<string[]>([]);
  const [reusableExclusions, setReusableExclusions] = useState<string[]>([]);

  useEffect(() => {
    async function loadProfile() {
      try {
        const data = profile || (await api.getProfile());
        setTripType(data.trip_type || 'Full week');
        setBudget(String(data.budget ?? 200));
        setAdults(data.adults ?? 4);
        setChildren(data.children ?? 0);
        setStores(data.preferred_stores || []);
        setMeals(data.meal_coverage || []);
        setCookingStyle(data.cooking_style || []);
        setDietaryRules(data.dietary_rules || []);
        setExclusions(data.exclusions || '');
        setPriceMode(data.price_mode || 'No prices');
        setPromptOverride(data.planner_prompt_override || '');
        setCustomInstructions(data.reusable_planning_instructions || '');
        setCustomStoreOptions(data.custom_store_options || []);
        setCustomCookingOptions(data.custom_cooking_style_options || []);
        setCustomMealOptions(data.custom_meal_coverage_options || []);
        setCustomDietaryTags(data.custom_dietary_tags || []);
        setReusableExclusions(data.reusable_exclusions || []);
      } catch (e) {
        console.error('Load profile', e);
      } finally {
        setLoading(false);
      }
    }

    loadProfile();
  }, [profile]);

  const allStores = useMemo(() => [...DEFAULT_STORES, ...customStoreOptions], [customStoreOptions]);
  const allMeals = useMemo(() => [...DEFAULT_MEAL_COVERAGE, ...customMealOptions], [customMealOptions]);
  const allCookingStyles = useMemo(() => [...DEFAULT_COOKING_STYLES, ...customCookingOptions], [customCookingOptions]);
  const allDietaryRules = useMemo(() => [...DEFAULT_DIETARY_RULES, ...customDietaryTags], [customDietaryTags]);
  const summary = `${adults + children} people • ${stores.length || 0} stores • ${meals.length || 0} meal types`;

  const toggle = (list: string[], setter: (next: string[]) => void, item: string) =>
    setter(list.includes(item) ? list.filter((entry) => entry !== item) : [...list, item]);

  const appendOption = (value: string, setter: (next: string[]) => void, current: string[], selectSetter?: (next: string[]) => void, selected?: string[]) => {
    const clean = value.trim();
    if (!clean) return;
    if (!current.includes(clean)) setter([...current, clean]);
    if (selectSetter && selected && !selected.includes(clean)) selectSetter([...selected, clean]);
  };

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      await api.generatePlan({
        trip_type: tripType,
        budget: parseFloat(budget) || 0,
        adults,
        children,
        preferred_stores: stores,
        meal_coverage: meals,
        cooking_style: cookingStyle,
        dietary_rules: dietaryRules,
        exclusions,
        price_mode: priceMode,
        prompt_override: promptOverride,
        custom_instructions: customInstructions,
        household_context_override: householdContextOverride,
        inventory_context_override: inventoryContextOverride,
        required_items_context_override: requiredItemsContextOverride,
        planning_notes: planningNotes,
        custom_store_options: customStoreOptions,
        custom_meal_coverage_options: customMealOptions,
        custom_cooking_style_options: customCookingOptions,
        custom_dietary_tags: customDietaryTags,
        reusable_exclusions: reusableExclusions,
        save_new_defaults: saveNewDefaults,
      });
      await refreshProfile();
      router.push('/plan-results');
    } catch (e: any) {
      Alert.alert('Plan generation failed', e.message);
    } finally {
      setGenerating(false);
    }
  };

  if (loading) {
    return (
      <SafeAreaView style={s.safe}>
        <View style={s.center}><ActivityIndicator size="large" color={Colors.primary} /></View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={s.safe}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={{ padding: gutter }}>
          <View style={[s.wrap, { maxWidth: contentMaxWidth }]}>
            <View style={s.header}>
              <Text style={s.title}>This Week</Text>
              <Text style={s.subtitle}>Build a pantry-aware plan with structured defaults and manual AI control when you need it.</Text>
              <View style={s.summaryRow}>
                <Text style={s.summaryText}>{summary}</Text>
              </View>
            </View>

            <InventorySnapshotCard />

            <View style={[s.grid, columns === 2 && s.gridDesktop]}>
              <View style={s.column}>
                <SectionCard title="Quick Setup" subtitle="Trip type, budget, and household size.">
                  <Label>Trip type</Label>
                  <View style={s.chipRow}>
                    {TRIP_TYPES.map((item) => {
                      const active = tripType === item;
                      return (
                        <TouchableOpacity key={item} style={[s.tripChip, active && s.tripChipOn]} onPress={() => setTripType(item)}>
                          <Text style={[s.tripChipText, active && s.tripChipTextOn]}>{item}</Text>
                        </TouchableOpacity>
                      );
                    })}
                  </View>

                  <Label>Budget</Label>
                  <View style={s.budgetWrap}>
                    <Text style={s.budgetSign}>$</Text>
                    <TextInput style={s.budgetInput} value={budget} onChangeText={setBudget} keyboardType="decimal-pad" />
                  </View>

                  <View style={columns === 2 ? s.stepperRow : undefined}>
                    <View style={s.stepperCell}>
                      <NumberStepper value={adults} onIncrement={() => setAdults((v) => v + 1)} onDecrement={() => setAdults((v) => Math.max(1, v - 1))} testID="week-adults" label="Adults" />
                    </View>
                    <View style={s.stepperCell}>
                      <NumberStepper value={children} onIncrement={() => setChildren((v) => v + 1)} onDecrement={() => setChildren((v) => Math.max(0, v - 1))} testID="week-children" label="Children" />
                    </View>
                  </View>
                </SectionCard>

                <SectionCard title="Preferences" subtitle="Stores, meal coverage, and cooking style.">
                  <Label>Preferred stores</Label>
                  <ChipSelector options={allStores} selected={stores} onToggle={(item) => toggle(stores, setStores, item)} testIDPrefix="store" />
                  <View style={s.inlineInputRow}>
                    <TextInput value={customStoreInput} onChangeText={setCustomStoreInput} placeholder="Add custom store" placeholderTextColor={Colors.textLight} style={s.inlineInput} />
                    <TouchableOpacity style={s.inlineBtn} onPress={() => { appendOption(customStoreInput, setCustomStoreOptions, customStoreOptions, setStores, stores); setCustomStoreInput(''); }}>
                      <Text style={s.inlineBtnText}>Add</Text>
                    </TouchableOpacity>
                  </View>

                  <Label>Meal coverage</Label>
                  <ChipSelector options={allMeals} selected={meals} onToggle={(item) => toggle(meals, setMeals, item)} testIDPrefix="meals" />
                  <View style={s.inlineInputRow}>
                    <TextInput value={customMealInput} onChangeText={setCustomMealInput} placeholder="Add meal coverage" placeholderTextColor={Colors.textLight} style={s.inlineInput} />
                    <TouchableOpacity style={s.inlineBtn} onPress={() => { appendOption(customMealInput, setCustomMealOptions, customMealOptions, setMeals, meals); setCustomMealInput(''); }}>
                      <Text style={s.inlineBtnText}>Add</Text>
                    </TouchableOpacity>
                  </View>

                  <Label>Cooking style</Label>
                  <ChipSelector options={allCookingStyles} selected={cookingStyle} onToggle={(item) => toggle(cookingStyle, setCookingStyle, item)} testIDPrefix="cooking" />
                  <View style={s.inlineInputRow}>
                    <TextInput value={customCookingInput} onChangeText={setCustomCookingInput} placeholder="Add cooking style" placeholderTextColor={Colors.textLight} style={s.inlineInput} />
                    <TouchableOpacity style={s.inlineBtn} onPress={() => { appendOption(customCookingInput, setCustomCookingOptions, customCookingOptions, setCookingStyle, cookingStyle); setCustomCookingInput(''); }}>
                      <Text style={s.inlineBtnText}>Add</Text>
                    </TouchableOpacity>
                  </View>
                </SectionCard>
              </View>

              <View style={s.column}>
                <SectionCard title="Advanced Preferences" subtitle="Food rules, exclusions, pricing, and AI controls.">
                  <Label>Dietary restrictions</Label>
                  <ChipSelector options={allDietaryRules} selected={dietaryRules} onToggle={(item) => toggle(dietaryRules, setDietaryRules, item)} testIDPrefix="dietary" />
                  <View style={s.inlineInputRow}>
                    <TextInput value={customDietaryInput} onChangeText={setCustomDietaryInput} placeholder="Add dietary tag" placeholderTextColor={Colors.textLight} style={s.inlineInput} />
                    <TouchableOpacity style={s.inlineBtn} onPress={() => { appendOption(customDietaryInput, setCustomDietaryTags, customDietaryTags, setDietaryRules, dietaryRules); setCustomDietaryInput(''); }}>
                      <Text style={s.inlineBtnText}>Add</Text>
                    </TouchableOpacity>
                  </View>

                  <Label>Exclusions</Label>
                  <TextInput style={s.textInput} multiline value={exclusions} onChangeText={setExclusions} placeholder="Ingredients or foods to avoid" placeholderTextColor={Colors.textLight} />
                  <View style={s.inlineInputRow}>
                    <TextInput value={customExclusionInput} onChangeText={setCustomExclusionInput} placeholder="Add reusable exclusion" placeholderTextColor={Colors.textLight} style={s.inlineInput} />
                    <TouchableOpacity style={s.inlineBtn} onPress={() => { appendOption(customExclusionInput, setReusableExclusions, reusableExclusions); setCustomExclusionInput(''); }}>
                      <Text style={s.inlineBtnText}>Save</Text>
                    </TouchableOpacity>
                  </View>
                  {!!reusableExclusions.length && (
                    <View style={s.savedRow}>
                      {reusableExclusions.map((item) => (
                        <TouchableOpacity key={item} style={s.savedChip} onPress={() => setExclusions(exclusions ? `${exclusions}, ${item}` : item)}>
                          <Text style={s.savedChipText}>{item}</Text>
                        </TouchableOpacity>
                      ))}
                    </View>
                  )}

                  <Label>Price mode</Label>
                  <View style={s.segmented}>
                    {PRICE_MODES.map((item) => {
                      const active = priceMode === item;
                      return (
                        <TouchableOpacity key={item} style={[s.seg, active && s.segOn]} onPress={() => setPriceMode(item)}>
                          <Text style={[s.segText, active && s.segTextOn]}>{item}</Text>
                        </TouchableOpacity>
                      );
                    })}
                  </View>

                  <TouchableOpacity style={s.advancedToggle} onPress={() => setShowAdvanced((v) => !v)}>
                    <Ionicons name={showAdvanced ? 'chevron-up' : 'chevron-down'} size={18} color={Colors.primary} />
                    <Text style={s.advancedToggleText}>Manual AI pipeline controls</Text>
                  </TouchableOpacity>

                  {showAdvanced && (
                    <View style={s.advancedPanel}>
                      <Label>Prompt override</Label>
                      <TextInput style={s.textInput} multiline value={promptOverride} onChangeText={setPromptOverride} placeholder="Optional planner prompt override" placeholderTextColor={Colors.textLight} />
                      <Label>Custom instructions</Label>
                      <TextInput style={s.textInput} multiline value={customInstructions} onChangeText={setCustomInstructions} placeholder="Reusable planning instructions" placeholderTextColor={Colors.textLight} />
                      <Label>Household context override</Label>
                      <TextInput style={s.textInput} multiline value={householdContextOverride} onChangeText={setHouseholdContextOverride} placeholder="Events, week constraints, guests, schedule shifts" placeholderTextColor={Colors.textLight} />
                      <Label>Inventory context override</Label>
                      <TextInput style={s.textInput} multiline value={inventoryContextOverride} onChangeText={setInventoryContextOverride} placeholder="Pantry notes not captured in structured inventory" placeholderTextColor={Colors.textLight} />
                      <Label>Required items override</Label>
                      <TextInput style={s.textInput} multiline value={requiredItemsContextOverride} onChangeText={setRequiredItemsContextOverride} placeholder="Required items context, store-specific instructions" placeholderTextColor={Colors.textLight} />
                      <Label>Extra planning notes</Label>
                      <TextInput style={s.textInput} multiline value={planningNotes} onChangeText={setPlanningNotes} placeholder="Temporary dietary changes, shopping priorities, budget exceptions" placeholderTextColor={Colors.textLight} />
                      <TouchableOpacity style={[s.saveDefaultsToggle, saveNewDefaults && s.saveDefaultsToggleOn]} onPress={() => setSaveNewDefaults((v) => !v)}>
                        <Text style={[s.saveDefaultsText, saveNewDefaults && s.saveDefaultsTextOn]}>{saveNewDefaults ? 'Will save new options into defaults' : 'Do not update defaults from this run'}</Text>
                      </TouchableOpacity>
                    </View>
                  )}
                </SectionCard>

                <SectionCard title="Build This Week" subtitle="Generate an editable plan and merged grocery output.">
                  <Text style={s.ctaCopy}>The planner will use pantry inventory, required items, household defaults, and any manual notes above.</Text>
                  <TouchableOpacity style={s.ctaBtn} onPress={handleGenerate} disabled={generating}>
                    {generating ? <ActivityIndicator color="#FFF" /> : <Text style={s.ctaText}>Build This Week&apos;s Plan</Text>}
                  </TouchableOpacity>
                </SectionCard>
              </View>
            </View>
          </View>
        </ScrollView>

        {!isDesktop && (
          <View style={s.ctaBar}>
            <TouchableOpacity style={s.ctaBtn} onPress={handleGenerate} disabled={generating}>
              {generating ? <ActivityIndicator color="#FFF" /> : <Text style={s.ctaText}>Build This Week&apos;s Plan</Text>}
            </TouchableOpacity>
          </View>
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: Colors.background },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  wrap: { width: '100%', alignSelf: 'center', gap: 16, paddingBottom: 120 },
  header: { gap: 8 },
  title: { fontSize: 32, fontWeight: '800', color: Colors.textMain, letterSpacing: -0.5 },
  subtitle: { fontSize: 15, lineHeight: 22, color: Colors.textMuted, maxWidth: 760 },
  summaryRow: { alignSelf: 'flex-start', backgroundColor: Colors.surface, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7, borderWidth: 1, borderColor: Colors.border },
  summaryText: { fontSize: 12.5, fontWeight: '700', color: Colors.primary },
  grid: { gap: 16 },
  gridDesktop: { flexDirection: 'row', alignItems: 'flex-start' },
  column: { flex: 1, gap: 16 },
  card: { backgroundColor: Colors.surface, borderRadius: 22, padding: 20, borderWidth: 1, borderColor: Colors.border, ...Shadows.sm },
  cardTitle: { fontSize: 18, fontWeight: '800', color: Colors.textMain },
  cardSubtitle: { fontSize: 13, lineHeight: 19, color: Colors.textMuted, marginTop: 4, marginBottom: 14 },
  label: { fontSize: 11, fontWeight: '800', color: Colors.textMuted, letterSpacing: 0.7, textTransform: 'uppercase', marginTop: 14, marginBottom: 10 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  tripChip: { paddingHorizontal: 14, paddingVertical: 9, borderRadius: 12, backgroundColor: Colors.surfaceMuted, borderWidth: 1, borderColor: 'transparent' },
  tripChipOn: { backgroundColor: Colors.primaryLight, borderColor: Colors.primary + '30' },
  tripChipText: { fontSize: 13, fontWeight: '600', color: Colors.textMuted },
  tripChipTextOn: { color: Colors.primary },
  budgetWrap: { flexDirection: 'row', alignItems: 'center', backgroundColor: Colors.surfaceMuted, borderRadius: 14, paddingHorizontal: 16 },
  budgetSign: { fontSize: 22, fontWeight: '800', color: Colors.primary },
  budgetInput: { flex: 1, fontSize: 24, fontWeight: '800', color: Colors.textMain, paddingVertical: 12, paddingHorizontal: 8 },
  stepperRow: { flexDirection: 'row', gap: 12, marginTop: 14 },
  stepperCell: { flex: 1, marginTop: 14 },
  segmented: { flexDirection: 'row', backgroundColor: Colors.surfaceMuted, borderRadius: 12, padding: 4, gap: 4 },
  seg: { flex: 1, paddingVertical: 10, borderRadius: 10, alignItems: 'center' },
  segOn: { backgroundColor: Colors.surface, ...Shadows.sm },
  segText: { fontSize: 12, fontWeight: '600', color: Colors.textMuted },
  segTextOn: { color: Colors.textMain },
  textInput: { minHeight: 88, backgroundColor: Colors.surfaceMuted, borderRadius: 14, paddingHorizontal: 14, paddingVertical: 12, textAlignVertical: 'top', color: Colors.textMain, fontSize: 14 },
  advancedToggle: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 12, marginTop: 8 },
  advancedToggleText: { fontSize: 14, fontWeight: '700', color: Colors.primary },
  advancedPanel: { paddingTop: 4 },
  inlineInputRow: { flexDirection: 'row', gap: 8, marginTop: 10 },
  inlineInput: { flex: 1, backgroundColor: Colors.surfaceMuted, borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12, fontSize: 14, color: Colors.textMain },
  inlineBtn: { backgroundColor: Colors.primary, borderRadius: 12, justifyContent: 'center', paddingHorizontal: 16 },
  inlineBtnText: { color: '#FFF', fontWeight: '700' },
  savedRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 10 },
  savedChip: { backgroundColor: Colors.primaryMuted, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 6 },
  savedChipText: { color: Colors.primary, fontSize: 12, fontWeight: '700' },
  saveDefaultsToggle: { backgroundColor: Colors.surfaceMuted, borderRadius: 12, padding: 12, marginTop: 12 },
  saveDefaultsToggleOn: { backgroundColor: Colors.primaryLight },
  saveDefaultsText: { color: Colors.textMuted, fontSize: 13, fontWeight: '700' },
  saveDefaultsTextOn: { color: Colors.primary },
  ctaCopy: { fontSize: 14, lineHeight: 21, color: Colors.textSecondary, marginBottom: 16 },
  ctaBar: { padding: 16, borderTopWidth: 1, borderTopColor: Colors.borderLight, backgroundColor: Colors.background },
  ctaBtn: { backgroundColor: Colors.accent, borderRadius: 16, alignItems: 'center', justifyContent: 'center', minHeight: 54, ...Shadows.accent },
  ctaText: { color: '#FFF', fontWeight: '800', fontSize: 15 },
});
