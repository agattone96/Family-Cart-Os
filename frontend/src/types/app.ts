export interface User {
  id: string;
  name: string;
  email: string;
}

export interface HouseholdProfile {
  id?: string;
  name?: string;
  email?: string;
  trip_type: string;
  budget: number;
  adults: number;
  children: number;
  preferred_stores: string[];
  meal_coverage: string[];
  cooking_style: string[];
  dietary_rules: string[];
  exclusions: string;
  price_mode: string;
  household_summary?: string;
  reusable_planning_instructions?: string;
  custom_store_options?: string[];
  custom_meal_coverage_options?: string[];
  custom_cooking_style_options?: string[];
  custom_dietary_tags?: string[];
  reusable_exclusions?: string[];
  planner_prompt_override?: string;
  onboarding_completed?: boolean;
  onboarding_completed_at?: string | null;
  expiring_soon_days?: number;
  last_inventory_location?: InventoryLocation | string;
}

export interface SessionState {
  token: string | null;
  user: User | null;
  profile: HouseholdProfile | null;
}

export type InventoryLocation = 'pantry' | 'fridge' | 'freezer';

export interface InventoryItem {
  id: string;
  name: string;
  normalized_name?: string;
  location: InventoryLocation;
  quantity?: number | null;
  unit?: string | null;
  category?: string | null;
  expiry_date?: string | null;
  low_stock_threshold?: number | null;
  notes?: string | null;
  archived_at?: string | null;
  created_at?: string;
  updated_at?: string;
  is_low_stock?: boolean;
  is_expiring_soon?: boolean;
}

export interface InventoryDashboard {
  expiring_soon_days: number;
  last_inventory_location: InventoryLocation | string;
  low_stock_count: number;
  expiring_soon_count: number;
  active_total: number;
  low_stock: InventoryItem[];
  expiring_soon: InventoryItem[];
}
