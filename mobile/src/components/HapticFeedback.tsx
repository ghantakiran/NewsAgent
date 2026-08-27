import React from 'react';
import { TouchableOpacity, TouchableOpacityProps } from 'react-native';
import * as Haptics from 'expo-haptics';

interface Props extends TouchableOpacityProps {
  hapticType?: 'light' | 'medium' | 'heavy' | 'selection';
}

export function HapticButton({ hapticType = 'light', onPress, children, ...props }: Props) {
  const handlePress = (e: any) => {
    switch (hapticType) {
      case 'selection':
        Haptics.selectionAsync();
        break;
      case 'light':
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        break;
      case 'medium':
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
        break;
      case 'heavy':
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
        break;
    }
    onPress?.(e);
  };

  return (
    <TouchableOpacity {...props} onPress={handlePress} activeOpacity={0.7}>
      {children}
    </TouchableOpacity>
  );
}
