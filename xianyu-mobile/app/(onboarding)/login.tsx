import { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  Pressable,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter } from 'expo-router';
import { useColorScheme } from 'react-native';
import { Eye, EyeOff } from 'lucide-react-native';
import { Button, Input, Card } from '@/components/ui';
import { colors, spacing, typography } from '@/lib/theme';
import { isTimeoutError, withTimeout } from '@/lib/timeout';
import { useAuthStore } from '@/stores/auth';
import { useConfigStore } from '@/stores/config';
import {
  login,
  extractUser,
  type LoginResponse,
} from '@/api/wrappers/auth';

export default function LoginScreen() {
  const scheme = useColorScheme();
  const c = colors[scheme === 'dark' ? 'dark' : 'light'];
  const router = useRouter();
  const setAuth = useAuthStore((s) => s.setAuth);
  const serverUrl = useConfigStore((s) => s.serverUrl);

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const [loading, setLoading] = useState(false);

  async function applyLoginResponse(resp: LoginResponse) {
    if (resp.success && resp.token) {
      const user = extractUser(resp);
      if (user) {
        await setAuth(resp.token, resp.refresh_token ?? '', user);
        router.replace('/(tabs)/messages');
      } else {
        Alert.alert('登录失败', '响应数据不完整');
      }
    } else {
      Alert.alert('登录失败', resp.message ?? '未知错误');
    }
  }

  async function handleAccountLogin() {
    if (!username.trim() || !password.trim()) {
      Alert.alert('提示', '请输入用户名和密码');
      return;
    }
    setLoading(true);
    try {
      const resp = await withTimeout(
        login(username.trim(), password),
        15000,
        'TIMEOUT_15S',
      );
      await applyLoginResponse(resp);
    } catch (e) {
      const msg = (e as Error).message;
      if (isTimeoutError(e)) {
        Alert.alert('登录超时', '连接服务器超时（15秒）。\n\n常见原因：域名解析到了不可达的 IPv6 地址。\n建议：返回服务器配置页改用 IP 地址连接');
      } else {
        Alert.alert('登录失败', msg);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: c.background }]}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={styles.content}
      >
        <ScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
        >
          <Text style={[styles.title, { color: c.text }]}>闲鱼管家</Text>
          <Text style={[styles.subtitle, { color: c.textSecondary }]}>
            {serverUrl ?? '未配置服务器'}
          </Text>

          <Card style={styles.form}>
            <Text style={[styles.label, { color: c.textSecondary }]}>用户名</Text>
            <Input
              value={username}
              onChangeText={setUsername}
              placeholder="admin"
              autoCapitalize="none"
              autoCorrect={false}
              style={styles.input}
            />
            <Text style={[styles.label, { color: c.textSecondary, marginTop: spacing.md }]}>密码</Text>
            <View style={styles.passwordRow}>
              <Input
                value={password}
                onChangeText={setPassword}
                placeholder="••••••••"
                secureTextEntry={!showPassword}
                style={styles.passwordInput}
              />
              <Pressable onPress={() => setShowPassword(!showPassword)} style={styles.eyeBtn}>
                {showPassword ? (
                  <Eye size={20} stroke={c.textSecondary} />
                ) : (
                  <EyeOff size={20} stroke={c.textSecondary} />
                )}
              </Pressable>
            </View>
          </Card>

          <Button label="登录" onPress={handleAccountLogin} loading={loading} />

        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  content: { flex: 1 },
  scroll: { padding: spacing.lg, gap: spacing.lg, flexGrow: 1 },
  title: { ...typography.title, textAlign: 'center', marginTop: spacing.xl },
  subtitle: { ...typography.caption, textAlign: 'center' },
  form: { gap: spacing.sm },
  label: { ...typography.caption },
  input: { marginTop: spacing.xs },
  passwordRow: { flexDirection: 'row', alignItems: 'center', marginTop: spacing.xs },
  passwordInput: { flex: 1, marginTop: 0 },
  eyeBtn: { padding: spacing.sm },
});
