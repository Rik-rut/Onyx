<script generics="ts">
export slot: 'item' | item: { title: string }
</script>
<span data-testid="card">{item.title}</span>
