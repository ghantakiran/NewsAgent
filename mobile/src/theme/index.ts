export const theme = {
  colors: {
    bgPrimary: '#07080a',
    bgSecondary: '#0c0d10',
    bgElevated: '#111318',
    bgHover: '#161820',
    borderSubtle: '#1c1e26',
    borderMedium: '#252833',
    borderAccent: '#2d3140',
    textPrimary: '#e8eaf0',
    textSecondary: '#9ba1b0',
    textMuted: '#5c6375',
    textDim: '#3d4255',
    accentRed: '#ff3b4e',
    accentGreen: '#00d68f',
    accentBlue: '#0ea5e9',
    accentGold: '#f5c542',
    accentPurple: '#a78bfa',
    // Category colors
    categoryGeneral: '#6b7394',
    categoryEarnings: '#f5c542',
    categoryUpgrade: '#00d68f',
    categoryDowngrade: '#ff3b4e',
    categoryMacro: '#0ea5e9',
    categoryFda: '#a78bfa',
    categoryMa: '#f97316',
    categoryIpo: '#06b6d4',
    categoryInsider: '#fb923c',
    categoryDividend: '#4ade80',
    categoryFiling: '#94a3b8',
    categoryCrypto: '#f59e0b',
    categoryTech: '#8b5cf6',
  },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 },
  fontSize: { xs: 10, sm: 12, md: 14, lg: 16, xl: 20, xxl: 24 },
  borderRadius: { sm: 4, md: 8, lg: 12, xl: 16, full: 100 },
};

export const CATEGORY_COLORS: Record<string, string> = {
  general: theme.colors.categoryGeneral,
  earnings: theme.colors.categoryEarnings,
  upgrade: theme.colors.categoryUpgrade,
  downgrade: theme.colors.categoryDowngrade,
  macro: theme.colors.categoryMacro,
  fda: theme.colors.categoryFda,
  ma: theme.colors.categoryMa,
  ipo: theme.colors.categoryIpo,
  insider: theme.colors.categoryInsider,
  dividend: theme.colors.categoryDividend,
  filing: theme.colors.categoryFiling,
  crypto: theme.colors.categoryCrypto,
  tech: theme.colors.categoryTech,
};

export function getCategoryColor(category: string): string {
  return CATEGORY_COLORS[category.toLowerCase()] ?? theme.colors.categoryGeneral;
}
