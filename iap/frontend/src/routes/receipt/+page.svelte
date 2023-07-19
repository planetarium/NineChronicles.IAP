<script>
  import {
    Button,
    Heading, ListPlaceholder,
    Table,
    TableBody,
    TableBodyCell,
    TableBodyRow,
    TableHead,
    TableHeadCell,
  } from 'flowbite-svelte';
  import {RECEIPT_STATUS_MAP, STAGE, STORE_MAP, TxStatus} from "../../const.js";
  import {DateTime} from "luxon";
  import Navigation from "../../components/Navigation.svelte";

  let receiptList = [];

  const fetchReceiptList = async () => {
    const resp = await fetch("/api/admin/receipt");
    receiptList = await resp.json();
    return receiptList;
  }

  const copyTxId = (txId) => {
    navigator.clipboard.writeText(txId).then(() => {
      console.log("copied")
    });
  };
</script>
<Navigation current="receipt"/>

<Table>
  <TableHead>
    <TableHeadCell>#</TableHeadCell>
    <TableHeadCell>Store</TableHeadCell>
    <TableHeadCell>Product Name</TableHeadCell>
    <TableHeadCell>Agent Addr</TableHeadCell>
    <TableHeadCell>Avatar Addr</TableHeadCell>
    <TableHeadCell>Receipt Status</TableHeadCell>
    <TableHeadCell>Tx. ID</TableHeadCell>
    <TableHeadCell>Tx. Status</TableHeadCell>
    <TableHeadCell>Purchase Timestamp</TableHeadCell>
  </TableHead>
  <TableBody class="divide-y">
    {#await fetchReceiptList()}
      <TableBodyRow>
        <TableBodyCell colspan="9">
          <ListPlaceholder divClass="p-4 space-y-4 rounded border border-gray-200 divide-y divide-gray-200 shadow animate-pulse dark:divide-gray-700 md:p-6 dark:border-gray-700"/>
        </TableBodyCell>
      </TableBodyRow>
    {:then receiptList}
      {#if receiptList.length === 0}
        <TableBodyRow>
          <TableBodyCell colspan=9 class="text-center">
            <Heading tag="h3">There is no receipt yet.</Heading>
          </TableBodyCell>
        </TableBodyRow>
      {:else}
        {#each receiptList as receipt, i}
          <TableBodyRow>
            <TableBodyCell>{i + 1}</TableBodyCell>
            <TableBodyCell>{STORE_MAP[receipt.store]}</TableBodyCell>
            <TableBodyCell>{receipt.product.name}</TableBodyCell>
            <TableBodyCell>{receipt.agent_addr}</TableBodyCell>
            <TableBodyCell>{receipt.avatar_addr}</TableBodyCell>
            <TableBodyCell>{RECEIPT_STATUS_MAP[receipt.status].Name}</TableBodyCell>
            <TableBodyCell>
              {receipt.tx_id ? receipt.tx_id.slice(0, 12) + "..." : ""}
              {#if receipt.tx_id}
                <Button color="purple" on:click={() => {copyTxId(receipt.tx_id)}}>Copy</Button>
              {/if}
            </TableBodyCell>
            <TableBodyCell>{receipt.tx_status ? TxStatus[receipt.tx_status] : ""}</TableBodyCell>
            <TableBodyCell>{DateTime.fromISO(receipt.purchased_at).toFormat("yyyy/MM/DD TT")}</TableBodyCell>
          </TableBodyRow>
        {/each}
      {/if}
    {/await}
  </TableBody>
</Table>
