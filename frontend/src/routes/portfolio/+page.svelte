<script lang="ts">
  import { onMount } from 'svelte';
  import type { PortfolioHolding } from '$lib/types';
  import { RefreshCw, Database, ChevronUp, ChevronDown } from 'lucide-svelte';

  let holdings: PortfolioHolding[] = [];
  let sortedHoldings: PortfolioHolding[] = [];
  let loading = true;
  let refreshing = false;
  let portfolioId: number | null = null;
  let lastLoadedPortfolioId: number | null = null;
  
  // Sorting state
  let sortColumn: string | null = null;
  let sortDirection: 'asc' | 'desc' = 'asc';

  async function loadHoldings() {
    loading = true;
    const params = new URLSearchParams();
    if (portfolioId !== null && portfolioId !== undefined) params.set('portfolio_id', String(portfolioId));
    const res = await fetch(`/api/portfolio/holdings?${params}`);
    const data = await res.json();
    holdings = data.holdings || [];
    lastLoadedPortfolioId = portfolioId;
    loading = false;
  }

  async function refreshHoldings() {
    refreshing = true;
    const params = new URLSearchParams();
    if (portfolioId !== null && portfolioId !== undefined) params.set('portfolio_id', String(portfolioId));
    params.set('sync', 'true');
    await fetch(`/api/portfolio/refresh?${params}`, { method: 'POST' });
    refreshing = false;
    await loadHoldings();
  }

  onMount(loadHoldings);

  $: (async () => {
    // react to portfolioId change
    if (portfolioId !== lastLoadedPortfolioId) {
      await loadHoldings();
    }
  })();

  function formatNumber(n?: number | null) {
    if (n === null || n === undefined) return '-';
    return new Intl.NumberFormat().format(n);
  }

  function formatPercent(n?: number | null) {
    if (n === null || n === undefined) return '-';
    return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`;
  }

  function handlePortfolioChange(e: Event) {
    const target = e.target as HTMLInputElement;
    const v = target?.value;
    portfolioId = v ? parseInt(v) : null;
  }

  function sortBy(column: string) {
    if (sortColumn === column) {
      // Toggle direction if same column
      sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
    } else {
      // New column, default to ascending
      sortColumn = column;
      sortDirection = 'asc';
    }
    applySorting();
  }

  function applySorting() {
    if (!sortColumn) {
      sortedHoldings = [...holdings];
      return;
    }

    sortedHoldings = [...holdings].sort((a, b) => {
      let aVal: any = getColumnValue(a, sortColumn!);
      let bVal: any = getColumnValue(b, sortColumn!);

      // Handle null/undefined values - put them at the end
      if (aVal === null || aVal === undefined) {
        if (bVal === null || bVal === undefined) return 0;
        return sortDirection === 'asc' ? 1 : -1;
      }
      if (bVal === null || bVal === undefined) {
        return sortDirection === 'asc' ? -1 : 1;
      }

      // For numeric columns, ensure numeric comparison
      const numericColumns = ['portfolio_id', 'pe', 'beta', 'volume', 'price', 'change'];
      if (numericColumns.includes(sortColumn!)) {
        const aNum = typeof aVal === 'number' ? aVal : parseFloat(aVal) || 0;
        const bNum = typeof bVal === 'number' ? bVal : parseFloat(bVal) || 0;
        const comparison = aNum - bNum;
        return sortDirection === 'desc' ? -comparison : comparison;
      }

      // For date columns
      if (sortColumn! === 'updated_at') {
        const aTime = aVal instanceof Date ? aVal.getTime() : 0;
        const bTime = bVal instanceof Date ? bVal.getTime() : 0;
        const comparison = aTime - bTime;
        return sortDirection === 'desc' ? -comparison : comparison;
      }

      // For string columns
      const aStr = String(aVal).toLowerCase();
      const bStr = String(bVal).toLowerCase();
      
      let comparison = 0;
      if (aStr < bStr) comparison = -1;
      else if (aStr > bStr) comparison = 1;

      return sortDirection === 'desc' ? -comparison : comparison;
    });
  }

  function getColumnValue(holding: PortfolioHolding, column: string): any {
    switch (column) {
      case 'portfolio_id': return holding.portfolio_id;
      case 'ticker': return holding.ticker;
      case 'company': return holding.company;
      case 'sector': return holding.sector;
      case 'industry': return holding.industry;
      case 'exchange': return holding.exchange;
      case 'pe': return holding.pe;
      case 'beta': return holding.beta;
      case 'volume': return holding.volume;
      case 'price': return holding.price;
      case 'change': return holding.change;
      case 'updated_at': return holding.updated_at ? new Date(holding.updated_at) : null;
      default: return '';
    }
  }

  // Reactive statement to update sorted holdings when holdings change
  $: {
    if (holdings.length > 0) {
      applySorting();
    } else {
      sortedHoldings = [];
    }
  }
</script>

<div class="space-y-6">
  <div class="flex items-center justify-between">
    <div>
      <h1 class="text-3xl font-bold text-gray-900 dark:text-white">Portfolio</h1>
      <p class="text-gray-600 dark:text-gray-400 mt-1">Holdings and fundamentals from Finviz</p>
    </div>
    <div class="flex items-center gap-2">
      <input
        type="number"
        class="input w-40"
        placeholder="Portfolio ID (optional)"
        on:change={handlePortfolioChange}
      />
      <button class="btn-secondary flex items-center gap-2" on:click={refreshHoldings} disabled={refreshing}>
        <RefreshCw class="h-4 w-4 {refreshing ? 'animate-spin' : ''}" />
        {refreshing ? 'Refreshing...' : 'Refresh Holdings'}
      </button>
    </div>
  </div>

  <div class="card p-6">
    <div class="flex items-center gap-2 mb-4">
      <Database class="h-5 w-5" />
      <h2 class="text-lg font-semibold">Holdings</h2>
    </div>

    {#if loading}
      <div class="space-y-2">
        {#each Array(5) as _}
          <div class="h-10 w-full rounded bg-gray-200 dark:bg-dark-800 animate-pulse" />
        {/each}
      </div>
    {:else if holdings.length === 0}
      <div class="p-8 text-center text-gray-500 dark:text-gray-400">No holdings found</div>
    {:else}
      <div class="overflow-x-auto">
        <table class="min-w-full text-sm">
          <thead>
            <tr class="text-left border-b border-gray-200 dark:border-dark-700">
              <th class="py-2 pr-4">
                <button 
                  class="flex items-center gap-1 font-semibold hover:text-primary-600 dark:hover:text-primary-400 transition-colors"
                  on:click={() => sortBy('portfolio_id')}
                >
                  Portfolio
                  {#if sortColumn === 'portfolio_id'}
                    {#if sortDirection === 'asc'}
                      <ChevronUp class="h-4 w-4" />
                    {:else}
                      <ChevronDown class="h-4 w-4" />
                    {/if}
                  {/if}
                </button>
              </th>
              <th class="py-2 pr-4">
                <button 
                  class="flex items-center gap-1 font-semibold hover:text-primary-600 dark:hover:text-primary-400 transition-colors"
                  on:click={() => sortBy('ticker')}
                >
                  Ticker
                  {#if sortColumn === 'ticker'}
                    {#if sortDirection === 'asc'}
                      <ChevronUp class="h-4 w-4" />
                    {:else}
                      <ChevronDown class="h-4 w-4" />
                    {/if}
                  {/if}
                </button>
              </th>
              <th class="py-2 pr-4">
                <button 
                  class="flex items-center gap-1 font-semibold hover:text-primary-600 dark:hover:text-primary-400 transition-colors"
                  on:click={() => sortBy('company')}
                >
                  Company
                  {#if sortColumn === 'company'}
                    {#if sortDirection === 'asc'}
                      <ChevronUp class="h-4 w-4" />
                    {:else}
                      <ChevronDown class="h-4 w-4" />
                    {/if}
                  {/if}
                </button>
              </th>
              <th class="py-2 pr-4">
                <button 
                  class="flex items-center gap-1 font-semibold hover:text-primary-600 dark:hover:text-primary-400 transition-colors"
                  on:click={() => sortBy('sector')}
                >
                  Sector
                  {#if sortColumn === 'sector'}
                    {#if sortDirection === 'asc'}
                      <ChevronUp class="h-4 w-4" />
                    {:else}
                      <ChevronDown class="h-4 w-4" />
                    {/if}
                  {/if}
                </button>
              </th>
              <th class="py-2 pr-4">
                <button 
                  class="flex items-center gap-1 font-semibold hover:text-primary-600 dark:hover:text-primary-400 transition-colors"
                  on:click={() => sortBy('industry')}
                >
                  Industry
                  {#if sortColumn === 'industry'}
                    {#if sortDirection === 'asc'}
                      <ChevronUp class="h-4 w-4" />
                    {:else}
                      <ChevronDown class="h-4 w-4" />
                    {/if}
                  {/if}
                </button>
              </th>
              <th class="py-2 pr-4">
                <button 
                  class="flex items-center gap-1 font-semibold hover:text-primary-600 dark:hover:text-primary-400 transition-colors"
                  on:click={() => sortBy('exchange')}
                >
                  Exchange
                  {#if sortColumn === 'exchange'}
                    {#if sortDirection === 'asc'}
                      <ChevronUp class="h-4 w-4" />
                    {:else}
                      <ChevronDown class="h-4 w-4" />
                    {/if}
                  {/if}
                </button>
              </th>
              <th class="py-2 pr-4">
                <button 
                  class="flex items-center gap-1 font-semibold hover:text-primary-600 dark:hover:text-primary-400 transition-colors"
                  on:click={() => sortBy('pe')}
                >
                  P/E
                  {#if sortColumn === 'pe'}
                    {#if sortDirection === 'asc'}
                      <ChevronUp class="h-4 w-4" />
                    {:else}
                      <ChevronDown class="h-4 w-4" />
                    {/if}
                  {/if}
                </button>
              </th>
              <th class="py-2 pr-4">
                <button 
                  class="flex items-center gap-1 font-semibold hover:text-primary-600 dark:hover:text-primary-400 transition-colors"
                  on:click={() => sortBy('beta')}
                >
                  Beta
                  {#if sortColumn === 'beta'}
                    {#if sortDirection === 'asc'}
                      <ChevronUp class="h-4 w-4" />
                    {:else}
                      <ChevronDown class="h-4 w-4" />
                    {/if}
                  {/if}
                </button>
              </th>
              <th class="py-2 pr-4">
                <button 
                  class="flex items-center gap-1 font-semibold hover:text-primary-600 dark:hover:text-primary-400 transition-colors"
                  on:click={() => sortBy('volume')}
                >
                  Volume
                  {#if sortColumn === 'volume'}
                    {#if sortDirection === 'asc'}
                      <ChevronUp class="h-4 w-4" />
                    {:else}
                      <ChevronDown class="h-4 w-4" />
                    {/if}
                  {/if}
                </button>
              </th>
              <th class="py-2 pr-4">
                <button 
                  class="flex items-center gap-1 font-semibold hover:text-primary-600 dark:hover:text-primary-400 transition-colors"
                  on:click={() => sortBy('price')}
                >
                  Price
                  {#if sortColumn === 'price'}
                    {#if sortDirection === 'asc'}
                      <ChevronUp class="h-4 w-4" />
                    {:else}
                      <ChevronDown class="h-4 w-4" />
                    {/if}
                  {/if}
                </button>
              </th>
              <th class="py-2 pr-4">
                <button 
                  class="flex items-center gap-1 font-semibold hover:text-primary-600 dark:hover:text-primary-400 transition-colors"
                  on:click={() => sortBy('change')}
                >
                  Change
                  {#if sortColumn === 'change'}
                    {#if sortDirection === 'asc'}
                      <ChevronUp class="h-4 w-4" />
                    {:else}
                      <ChevronDown class="h-4 w-4" />
                    {/if}
                  {/if}
                </button>
              </th>
              <th class="py-2 pr-4">
                <button 
                  class="flex items-center gap-1 font-semibold hover:text-primary-600 dark:hover:text-primary-400 transition-colors"
                  on:click={() => sortBy('updated_at')}
                >
                  Updated
                  {#if sortColumn === 'updated_at'}
                    {#if sortDirection === 'asc'}
                      <ChevronUp class="h-4 w-4" />
                    {:else}
                      <ChevronDown class="h-4 w-4" />
                    {/if}
                  {/if}
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            {#each sortedHoldings as h}
              <tr class="border-b border-gray-100 dark:border-dark-800">
                <td class="py-2 pr-4">{h.portfolio_id}</td>
                <td class="py-2 pr-4 font-semibold">{h.ticker}</td>
                <td class="py-2 pr-4">{h.company}</td>
                <td class="py-2 pr-4">{h.sector || '-'}</td>
                <td class="py-2 pr-4">{h.industry || '-'}</td>
                <td class="py-2 pr-4">{h.exchange || '-'}</td>
                <td class="py-2 pr-4">{h.pe ?? '-'}</td>
                <td class="py-2 pr-4">{h.beta ?? '-'}</td>
                <td class="py-2 pr-4">{formatNumber(h.volume)}</td>
                <td class="py-2 pr-4">{h.price ?? '-'}</td>
                <td class="py-2 pr-4" class:text-success-600={h.change !== null && h.change !== undefined && h.change > 0} class:text-danger-600={h.change !== null && h.change !== undefined && h.change < 0}>{formatPercent(h.change)}</td>
                <td class="py-2 pr-4">{h.updated_at ? new Date(h.updated_at).toLocaleString() : '-'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </div>
</div>


