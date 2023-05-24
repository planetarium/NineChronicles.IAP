<script>
  import {onMount} from "svelte";
  import {
    A,
    Badge,
    Heading, Hr,
    Spinner,
    Table,
    TableBody,
    TableBodyCell,
    TableBodyRow,
    TableHead,
    TableHeadCell
  } from 'flowbite-svelte';
  import {BoxStatusColorMap, BoxStatusNameMap} from "../../const.js";

  let itemList = [];
  let boxList = [];

  const fetchBoxList = async () => {
    const resp = await fetch("/api/box");
    const data = await resp.json();
    if (resp.ok) {
      boxList = data;
      return boxList;
    } else {
      throw new Error(data);
    }
  };

  onMount(async () => {
    const resp = await Promise.all([fetch("/api/box"), fetch("/api/item")]);
    [boxList, itemList] = await Promise.all(resp.map(r => r.json()));
  })
</script>
<Heading tag="h1">This is box view</Heading>
<Table>
  <TableHead
      class="border-b-2 border-purple-700 text-center text-gray-700 uppercase bg-gray-100 dark:bg-gray-700 dark:text-gray-400">
    <TableHeadCell>Box ID</TableHeadCell>
    <TableHeadCell>Box Name</TableHeadCell>
    <TableHeadCell>Price (NCG)</TableHeadCell>
    <TableHeadCell>Status</TableHeadCell>
  </TableHead>
  <TableBody class="divide-y">
    {#await fetchBoxList()}
      <TableBodyRow>
        <TableBodyCell colspan="4" class="text-center">
          <Spinner class="text-center"></Spinner>
        </TableBodyCell>
      </TableBodyRow>
    {:then boxList}
      {#if boxList.length === 0}
        <TableBodyRow>
          <TableBodyCell colspan="4" class="text-center">
            There is no box at all.
          </TableBodyCell>
        </TableBodyRow>
      {:else}
        {#each boxList as box}
          <TableBodyRow color={box.status >= 90? "red" : "none"}>
            <TableBodyCell>{box.id}</TableBodyCell>
            <TableBodyCell>{box.name}</TableBodyCell>
            <TableBodyCell>{box.price}</TableBodyCell>
            <TableBodyCell>
              <Badge color={BoxStatusColorMap[box.status]}>{BoxStatusNameMap[box.status]}</Badge>
            </TableBodyCell>
          </TableBodyRow>
        {/each}
      {/if}
    {/await}
  </TableBody>
</Table>
<Hr></Hr>
<A href="/">Home</A>
