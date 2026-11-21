<script generics="ts">
import ProbeCard from './ProbeCard.svelte';
const row = [{ title: 'A' }, { title: 'B' }];
</script>
{#each row as r}<ProbeCard item={r} />{/each}
