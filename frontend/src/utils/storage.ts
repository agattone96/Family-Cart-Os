import AsyncStorage from '@react-native-async-storage/async-storage';

export const storageKeys = {
  authToken: 'diana.authToken',
  lastInventoryLocation: 'diana.lastInventoryLocation',
};

export const storage = {
  get: (key: string) => AsyncStorage.getItem(key),
  set: (key: string, value: string) => AsyncStorage.setItem(key, value),
  remove: (key: string) => AsyncStorage.removeItem(key),
};
