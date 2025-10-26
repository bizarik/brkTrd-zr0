<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import {
		Menu,
		X,
		TrendingUp,
		Newspaper,
		BarChart3,
		Settings,
		Moon,
		Sun,
		Bell,
		RefreshCw,
		Zap,
		LineChart,
		DatabaseZap
	} from 'lucide-svelte';
	import { theme } from '$lib/stores/theme';
	import { websocket } from '$lib/stores/websocket';

	let sidebarOpen = false;
	let notificationsOpen = false;
	let refreshing = false;

	const navigation = [
		{ name: 'Dashboard', href: '/', icon: BarChart3 },
		{ name: 'Headlines', href: '/headlines', icon: Newspaper },
		{ name: 'Opportunities', href: '/opportunities', icon: TrendingUp },
		{ name: 'Portfolio', href: '/portfolio', icon: BarChart3 },
		{ name: 'Returns', href: '/returns', icon: LineChart },
		{ name: 'Settings', href: '/settings', icon: Settings }
	];

	onMount(() => {
		// Initialize theme
		const savedTheme = (localStorage.getItem('theme') || 'dark') as 'light' | 'dark';
		theme.set(savedTheme);
		document.documentElement.classList.toggle('dark', savedTheme === 'dark');

		// Connect WebSocket
		websocket.connect();

		return () => {
			websocket.disconnect();
		};
	});

	function toggleTheme() {
		theme.update((t) => {
			const newTheme = t === 'dark' ? 'light' : 'dark';
			localStorage.setItem('theme', newTheme);
			document.documentElement.classList.toggle('dark', newTheme === 'dark');
			return newTheme;
		});
	}

	async function handleRefresh() {
		refreshing = true;
		// Trigger data refresh
		await fetch('/api/headlines/fetch', { method: 'POST' });
		setTimeout(() => {
			refreshing = false;
		}, 2000);
	}
  // Use $page store for route info; no props expected
</script>

<div class="min-h-screen bg-gradient-to-br from-gray-50 to-gray-100 dark:from-dark-950 dark:to-dark-900">
	<!-- Mobile sidebar backdrop -->
	{#if sidebarOpen}
		<div
			role="button"
			tabindex="-1"
			class="fixed inset-0 z-40 bg-black/50 lg:hidden"
			on:click={() => (sidebarOpen = false)}
			on:keydown={(e) => e.key === 'Escape' && (sidebarOpen = false)}
		/>
	{/if}

	<!-- Sidebar -->
	<div
		class="fixed inset-y-0 left-0 z-50 w-64 transform transition-transform duration-300 lg:translate-x-0
		       {sidebarOpen ? 'translate-x-0' : '-translate-x-full'}"
	>
		<div class="flex h-full flex-col glass">
			<!-- Logo -->
			<div class="flex h-16 items-center justify-between px-6 border-b border-gray-200 dark:border-dark-700">
				<div class="flex items-center space-x-2">
					<Zap class="h-8 w-8 text-primary-500" />
					<span class="text-xl font-bold gradient-text">brākTrād</span>
				</div>
				<button
					class="lg:hidden p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-dark-800"
					on:click={() => (sidebarOpen = false)}
				>
					<X class="h-5 w-5" />
				</button>
			</div>

			<!-- Navigation -->
			<nav class="flex-1 space-y-1 px-3 py-4">
				{#each navigation as item}
					<a
						href={item.href}
						class="flex items-center space-x-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors
						       {$page.url.pathname === item.href
							? 'bg-primary-100 text-primary-900 dark:bg-primary-900/30 dark:text-primary-300'
							: 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-dark-800'}"
					>
						<svelte:component this={item.icon} class="h-5 w-5" />
						<span>{item.name}</span>
					</a>
				{/each}
				
			<!-- Database Tools Section -->
			<div class="pt-4">
				<a
					href="/database"
					class="flex items-center space-x-3 rounded-lg px-3 py-2 text-xs font-medium transition-colors
					       {$page.url.pathname.includes('database')
						? 'bg-primary-100 text-primary-900 dark:bg-primary-900/30 dark:text-primary-300'
						: 'text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-dark-800'}"
				>
					<DatabaseZap class="h-4 w-4" />
					<span>Database Explorer</span>
				</a>
			</div>
			</nav>

			<!-- Footer -->
			<div class="border-t border-gray-200 dark:border-dark-700 p-4">
				<div class="flex items-center justify-between">
					<button
						class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-dark-800 transition-colors"
						on:click={toggleTheme}
						aria-label="Toggle theme"
					>
						{#if $theme === 'dark'}
							<Sun class="h-5 w-5 text-amber-500" />
						{:else}
							<Moon class="h-5 w-5 text-indigo-600" />
						{/if}
					</button>

					<button
						class="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-dark-800 transition-colors
						       {refreshing ? 'animate-spin' : ''}"
						on:click={handleRefresh}
						aria-label="Refresh data"
					>
						<RefreshCw class="h-5 w-5" />
					</button>

					<button
						class="relative p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-dark-800 transition-colors"
						on:click={() => (notificationsOpen = !notificationsOpen)}
						aria-label="Notifications"
					>
						<Bell class="h-5 w-5" />
						<span class="absolute top-1 right-1 h-2 w-2 rounded-full bg-danger-500 animate-pulse" />
					</button>
				</div>
			</div>
		</div>
	</div>

	<!-- Main content -->
	<div class="lg:pl-64">
		<!-- Top bar -->
		<header class="sticky top-0 z-30 glass border-b border-gray-200 dark:border-dark-700">
			<div class="flex h-16 items-center justify-between px-4 sm:px-6 lg:px-8">
				<button
					class="lg:hidden p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-dark-800"
					on:click={() => (sidebarOpen = true)}
				>
					<Menu class="h-5 w-5" />
				</button>

				<div class="flex items-center space-x-4">
					<div class="flex items-center space-x-2">
						<div class="h-2 w-2 rounded-full bg-success-500 animate-pulse" />
						<span class="text-sm text-gray-600 dark:text-gray-400">Live</span>
					</div>
				</div>
			</div>
		</header>

		<!-- Page content -->
		<main class="p-4 sm:p-6 lg:p-8">
			<slot />
		</main>
	</div>

	<!-- Notifications dropdown -->
	{#if notificationsOpen}
		<div class="fixed top-20 right-4 z-40 w-80 card p-4 animate-slide-down">
			<h3 class="font-semibold mb-3">Notifications</h3>
			<div class="space-y-2">
				<div class="p-3 rounded-lg bg-success-50 dark:bg-success-900/20">
					<p class="text-sm text-success-800 dark:text-success-300">
						New opportunity: AAPL long signal
					</p>
					<p class="text-xs text-gray-600 dark:text-gray-400 mt-1">2 minutes ago</p>
				</div>
				<div class="p-3 rounded-lg bg-blue-50 dark:bg-blue-900/20">
					<p class="text-sm text-blue-800 dark:text-blue-300">
						Sentiment analysis complete
					</p>
					<p class="text-xs text-gray-600 dark:text-gray-400 mt-1">5 minutes ago</p>
				</div>
			</div>
		</div>
	{/if}
</div>
