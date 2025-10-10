<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import {
		TrendingUp,
		TrendingDown,
		BarChart,
		RefreshCw,
		Clock,
		Filter,
		Upload
	} from 'lucide-svelte';
	import type { PageData } from './$types';
	import { websocket } from '$lib/stores/websocket';
	import ReturnCell from '$lib/components/ReturnCell.svelte';
	import SentimentReturnsChart from '$lib/components/SentimentReturnsChart.svelte';
	import HistoricalReturnsChart from '$lib/components/HistoricalReturnsChart.svelte';

	let loading = true;
	let error: string | null = null;
	let activeTab: 'historical' | 'sentiment' = 'sentiment';
	let selectedTicker: string | null = null;
	let timeframe: string = '7d';
	let minConfidence: number = 0.6;
	let calculating = false;
	let uploading = false;
	let uploadMessage: string | null = null;

	// Data stores
	let sentimentReturns: any[] = [];
	let historicalReturns: any[] = [];
	let availableTickers: { ticker: string; company: string }[] = [];
	
	// File upload
	let fileInput: HTMLInputElement;

	onMount(async () => {
		await loadTickers();
		loading = false;
	});

	async function loadTickers() {
		try {
			const response = await fetch('/api/returns/tickers');
			if (!response.ok) {
				throw new Error('Failed to fetch tickers');
			}
			const data = await response.json();
			availableTickers = data.tickers;
		} catch (e) {
			console.error('Error loading tickers:', e);
			error = 'Failed to load tickers';
		}
	}

	async function loadData() {
		try {
			if (selectedTicker) {
				const [sentimentRes, historicalRes] = await Promise.all([
					fetch(`/api/returns/sentiment/ticker/${selectedTicker}?days=${timeframe === '7d' ? 7 : 30}&min_confidence=${minConfidence}`),
					fetch(`/api/returns/historical/${selectedTicker}?days=${timeframe === '7d' ? 7 : 30}`)
				]);

				if (!sentimentRes.ok || !historicalRes.ok) {
					throw new Error('Failed to fetch data');
				}

				const sentimentData = await sentimentRes.json();
				const historicalData = await historicalRes.json();

				sentimentReturns = sentimentData.sentiment_returns;
				historicalReturns = historicalData.returns;
			}
		} catch (e) {
			console.error('Error loading data:', e);
			error = 'Failed to load data';
		}
	}

	function handleTickerSelect(event: Event) {
		selectedTicker = (event.target as HTMLSelectElement).value;
		loadData();
	}

	function handleTimeframeChange(newTimeframe: string) {
		timeframe = newTimeframe;
		loadData();
	}

	function handleConfidenceChange(event: Event) {
		minConfidence = parseFloat((event.target as HTMLInputElement).value);
		loadData();
	}

	async function calculateReturnsForTicker() {
		if (!selectedTicker) {
			error = 'Please select a ticker first';
			return;
		}

		calculating = true;
		error = null;

		try {
			// Get all headlines with sentiment for this ticker
			const headlinesRes = await fetch(`/api/headlines?ticker=${selectedTicker}&has_sentiment=true&limit=100`);
			if (!headlinesRes.ok) {
				throw new Error('Failed to fetch headlines');
			}

			const headlinesData = await headlinesRes.json();
			const headlines = headlinesData.headlines || [];

			if (headlines.length === 0) {
				error = 'No headlines with sentiment analysis found for this ticker';
				calculating = false;
				return;
			}

			// Calculate returns for each headline
			let successCount = 0;
			let errorCount = 0;

			for (const headline of headlines) {
				try {
					const calcRes = await fetch(`/api/returns/calculate/${headline.id}`, {
						method: 'POST'
					});

					if (calcRes.ok) {
						successCount++;
					} else {
						errorCount++;
					}
				} catch (e) {
					errorCount++;
				}
			}

			// Reload data
			await loadData();

			if (successCount > 0) {
				error = null;
			} else if (errorCount > 0) {
				error = `Calculated returns for ${successCount} headlines (${errorCount} failed)`;
			}
		} catch (e) {
			console.error('Error calculating returns:', e);
			error = 'Failed to calculate returns';
		} finally {
			calculating = false;
		}
	}

	async function handleUploadQuoteData() {
		if (!selectedTicker) {
			uploadMessage = 'Please select a ticker first';
			return;
		}
		
		if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
			uploadMessage = 'Please select a CSV file';
			return;
		}

		uploading = true;
		uploadMessage = null;
		error = null;

		try {
			const formData = new FormData();
			formData.append('file', fileInput.files[0]);
			formData.append('ticker', selectedTicker);

			const response = await fetch('/api/returns/upload-quote-data', {
				method: 'POST',
				body: formData
			});

			if (!response.ok) {
				const errorData = await response.json();
				throw new Error(errorData.detail || 'Upload failed');
			}

			const result = await response.json();
			uploadMessage = `✓ ${result.message} (${result.rows_stored} new, ${result.rows_updated} updated)`;
			
			// Clear file input
			if (fileInput) {
				fileInput.value = '';
			}

			// Reload tickers and data
			await loadTickers();
			if (selectedTicker) {
				await loadData();
			}
		} catch (e) {
			console.error('Error uploading quote data:', e);
			uploadMessage = `✗ ${e instanceof Error ? e.message : 'Upload failed'}`;
		} finally {
			uploading = false;
		}
	}

	function triggerFileUpload() {
		fileInput?.click();
	}

	$: {
		// Reactive statement to handle websocket updates
		if ($websocket.data?.type === 'new_sentiment') {
			loadData();
		}
	}
</script>

<div class="space-y-6">
	<!-- Header -->
	<div class="flex items-center justify-between">
		<h1 class="text-2xl font-bold text-gray-900 dark:text-gray-100">Returns Analysis</h1>
		<div class="flex items-center space-x-4">
			<div class="flex items-center space-x-2">
				<label for="ticker-select" class="sr-only">Select Ticker</label>
				<select
					id="ticker-select"
					class="rounded-lg border border-gray-300 dark:border-dark-700 bg-white dark:bg-dark-800 px-3 py-2"
					on:change={handleTickerSelect}
					bind:value={selectedTicker}
				>
					<option value="">Select Ticker</option>
					{#each availableTickers as ticker}
						<option value={ticker.ticker}>
							{ticker.ticker} - {ticker.company}
						</option>
					{/each}
				</select>
			</div>

			{#if selectedTicker}
				<button
					class="flex items-center space-x-2 px-4 py-2 rounded-lg bg-success-500 text-white hover:bg-success-600 transition-colors disabled:opacity-50"
					on:click={triggerFileUpload}
					disabled={uploading}
					title="Upload Finviz quote CSV for {selectedTicker}"
				>
					{#if uploading}
						<RefreshCw class="h-4 w-4 animate-spin" />
						<span>Uploading...</span>
					{:else}
						<Upload class="h-4 w-4" />
						<span>Upload Quote Data</span>
					{/if}
				</button>
				<input
					type="file"
					accept=".csv"
					bind:this={fileInput}
					on:change={handleUploadQuoteData}
					class="hidden"
				/>
				
				<button
					class="flex items-center space-x-2 px-4 py-2 rounded-lg bg-primary-500 text-white hover:bg-primary-600 transition-colors disabled:opacity-50"
					on:click={calculateReturnsForTicker}
					disabled={calculating}
				>
					{#if calculating}
						<RefreshCw class="h-4 w-4 animate-spin" />
						<span>Calculating...</span>
					{:else}
						<BarChart class="h-4 w-4" />
						<span>Calculate Returns</span>
					{/if}
				</button>
			{/if}
			
			<div class="flex items-center space-x-2">
				<button
					class="p-2 rounded-lg text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-dark-800 transition-colors"
					on:click={loadData}
					title="Refresh data"
				>
					<RefreshCw class="h-5 w-5" />
				</button>
			</div>

			<div class="flex items-center space-x-2 rounded-lg border border-gray-300 dark:border-dark-700 p-1">
				<button
					class="px-3 py-1 rounded-md transition-colors {timeframe === '7d'
						? 'bg-primary-100 text-primary-900 dark:bg-primary-900/30 dark:text-primary-300'
						: 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-dark-800'}"
					on:click={() => handleTimeframeChange('7d')}
				>
					7D
				</button>
				<button
					class="px-3 py-1 rounded-md transition-colors {timeframe === '30d'
						? 'bg-primary-100 text-primary-900 dark:bg-primary-900/30 dark:text-primary-300'
						: 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-dark-800'}"
					on:click={() => handleTimeframeChange('30d')}
				>
					30D
				</button>
			</div>
		</div>
	</div>

	<!-- Tabs -->
	<div class="border-b border-gray-200 dark:border-dark-700">
		<nav class="-mb-px flex space-x-8">
			<button
				class="whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium transition-colors {activeTab === 'sentiment'
					? 'border-primary-500 text-primary-600 dark:text-primary-400'
					: 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300'}"
				on:click={() => (activeTab = 'sentiment')}
			>
				Sentiment Returns
			</button>
			<button
				class="whitespace-nowrap border-b-2 py-4 px-1 text-sm font-medium transition-colors {activeTab === 'historical'
					? 'border-primary-500 text-primary-600 dark:text-primary-400'
					: 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-300'}"
				on:click={() => (activeTab = 'historical')}
			>
				Historical Returns
			</button>
		</nav>
	</div>

	<!-- Upload Message -->
	{#if uploadMessage}
		<div class="rounded-lg p-4 {uploadMessage.startsWith('✓') 
			? 'bg-success-50 dark:bg-success-900/30 text-success-700 dark:text-success-400' 
			: 'bg-warning-50 dark:bg-warning-900/30 text-warning-700 dark:text-warning-400'}">
			{uploadMessage}
		</div>
	{/if}

	<!-- Content -->
	{#if loading}
		<div class="flex items-center justify-center py-12">
			<RefreshCw class="h-8 w-8 animate-spin text-primary-500" />
		</div>
	{:else if error}
		<div class="rounded-lg bg-danger-50 dark:bg-danger-900/30 p-4 text-danger-700 dark:text-danger-400">
			{error}
		</div>
	{:else if !selectedTicker}
		<div class="text-center py-12 text-gray-500 dark:text-gray-400">
			Select a ticker to view returns analysis
		</div>
	{:else if activeTab === 'sentiment'}
		<div class="space-y-6">
			<!-- Sentiment Returns Controls -->
			<div class="flex items-center space-x-4">
				<div class="flex items-center space-x-2">
					<label for="confidence-range" class="text-sm text-gray-700 dark:text-gray-300">Min Confidence:</label>
					<input
						id="confidence-range"
						type="range"
						min="0"
						max="1"
						step="0.1"
						value={minConfidence}
						on:change={handleConfidenceChange}
						class="w-32"
					/>
					<span class="text-sm text-gray-600 dark:text-gray-400">{minConfidence}</span>
				</div>
			</div>

			<!-- Sentiment Returns Chart -->
			<div class="rounded-lg border border-gray-200 dark:border-dark-700 bg-white dark:bg-dark-800 p-4">
				<SentimentReturnsChart data={sentimentReturns} timeframe={timeframe} />
			</div>

			<!-- Sentiment Returns Table -->
			<div class="rounded-lg border border-gray-200 dark:border-dark-700 bg-white dark:bg-dark-800 overflow-hidden">
				<table class="min-w-full divide-y divide-gray-200 dark:divide-dark-700">
					<thead class="bg-gray-50 dark:bg-dark-850">
						<tr>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								Date
							</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								Headline
							</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								Sentiment
							</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								3h
							</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								24h
							</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								Next Day
							</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								2d
							</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								3d
							</th>
						</tr>
					</thead>
					<tbody class="bg-white dark:bg-dark-800 divide-y divide-gray-200 dark:divide-dark-700">
						{#each sentimentReturns as row}
							<tr class="hover:bg-gray-50 dark:hover:bg-dark-750">
								<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-gray-100">
									{new Date(row.timestamp).toLocaleDateString()}
								</td>
								<td class="px-6 py-4 text-sm text-gray-500 dark:text-gray-400">
									{row.headline}
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm">
									<div class="flex items-center space-x-2">
										<span
											class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium {row.sentiment.value > 0
												? 'bg-success-100 text-success-800 dark:bg-success-900/30 dark:text-success-400'
												: row.sentiment.value < 0
												? 'bg-danger-100 text-danger-800 dark:bg-danger-900/30 dark:text-danger-400'
												: 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200'}"
										>
											{row.sentiment.value > 0
												? 'Positive'
												: row.sentiment.value < 0
												? 'Negative'
												: 'Neutral'}
										</span>
										<span class="text-gray-500 dark:text-gray-400">
											({(row.sentiment.confidence * 100).toFixed(1)}%)
										</span>
									</div>
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm">
									<ReturnCell value={row.returns['3h']} />
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm">
									<ReturnCell value={row.returns['24h']} />
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm">
									<ReturnCell value={row.returns.next_day} />
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm">
									<ReturnCell value={row.returns['2d']} />
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm">
									<ReturnCell value={row.returns['3d']} />
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{:else}
		<div class="space-y-6">
			<!-- Historical Returns Chart -->
			<div class="rounded-lg border border-gray-200 dark:border-dark-700 bg-white dark:bg-dark-800 p-4">
				<HistoricalReturnsChart data={historicalReturns} />
			</div>

			<!-- Historical Returns Table -->
			<div class="rounded-lg border border-gray-200 dark:border-dark-700 bg-white dark:bg-dark-800 overflow-hidden">
				<table class="min-w-full divide-y divide-gray-200 dark:divide-dark-700">
					<thead class="bg-gray-50 dark:bg-dark-850">
						<tr>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								Date
							</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								Return
							</th>
							<th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
								Volume
							</th>
						</tr>
					</thead>
					<tbody class="bg-white dark:bg-dark-800 divide-y divide-gray-200 dark:divide-dark-700">
						{#each historicalReturns as row}
							<tr class="hover:bg-gray-50 dark:hover:bg-dark-750">
								<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-gray-100">
									{new Date(row.date).toLocaleDateString()}
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm">
									<ReturnCell value={row.return} />
								</td>
								<td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
									{row.volume.toLocaleString()}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}
</div>
