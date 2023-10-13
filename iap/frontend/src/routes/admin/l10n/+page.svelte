<script>
  import Navigation from "../../../components/Navigation.svelte";
  import {
    Button,
    Input, Spinner,
    TabItem,
    Table,
    TableBody,
    TableBodyCell,
    TableBodyRow,
    TableHead,
    TableHeadCell,
    Tabs
  } from "flowbite-svelte";
  import {onMount} from "svelte";

  let uploading = false;
  export let category = {header: [], body: []};
  export let product = {header: [], body: []};

  onMount(async () => {
    let  resp = await fetch("/api/admin/l10n/csv/category");
    category = await resp.json();
    resp = await fetch("/api/admin/l10n/csv/product");
    product = await resp.json();
  });

  const saveCategory = async (e) => {
    if (confirm("Save category contents?")) {
      uploading = true;
      const result = await fetch("/api/admin/l10n/csv/category", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(category)
      });
      alert(await result.json());
      uploading = false;
    }
  }

</script>
<Navigation current="l10n"></Navigation>
<Tabs>
  <TabItem open title="Category">
    {#if category.header.length === 0}
      Wait for fetching data...
    {:else }
      <Table>
        <TableHead>
          {#each category.header as header}
            <TableHeadCell>{header}</TableHeadCell>
          {/each}
        </TableHead>
        <TableBody>
          {#each category.body as body}
            <TableBodyRow>
              {#each body as data}
                <TableBodyCell><Input bind:value={data}/></TableBodyCell>
              {/each}
            </TableBodyRow>
          {/each}
        </TableBody>
      </Table>
    {/if}
    <Button on:click={saveCategory} bind:disabled={uploading}>
      {#if uploading}
        <Spinner size="4" class="mr-3"/>
        Uploading...
      {:else}
        Upload
      {/if}
    </Button>
  </TabItem>
  <TabItem title="Product">Product</TabItem>
</Tabs>
